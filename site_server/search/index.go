package search

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/blugelabs/bluge"
)

// IndexNeedsBuild reports whether the index is missing or older than its source.
//
// Only the command-line entry point asks: a serverless function must never try to
// build, so it never calls this.
func IndexNeedsBuild(sourcePath, indexDir string) bool {
	sourceInfo, err := os.Stat(sourcePath)
	if err != nil {
		return true
	}
	raw, err := os.ReadFile(indexDir + ".stamp.json")
	if err != nil {
		return true
	}
	var stamp indexStamp
	if json.Unmarshal(raw, &stamp) != nil {
		return true
	}
	return stamp.SourceSize != sourceInfo.Size() || stamp.SourceModUnix != sourceInfo.ModTime().UnixNano()
}

// BuildIndex streams the JSONL source into a fresh Bluge index, writing to a
// temporary directory and swapping it into place so an interrupted build never
// leaves a half-written index behind.
func BuildIndex(sourcePath, indexDir string) error {
	source, err := os.Open(sourcePath)
	if err != nil {
		return err
	}
	defer source.Close()
	info, err := source.Stat()
	if err != nil {
		return err
	}

	temporary := indexDir + ".building"
	if err := os.RemoveAll(temporary); err != nil {
		return err
	}
	writer, err := bluge.OpenWriter(bluge.DefaultConfig(temporary))
	if err != nil {
		return err
	}

	scanner := bufio.NewScanner(source)
	scanner.Buffer(make([]byte, 64*1024), 64*1024*1024)
	batch := bluge.NewBatch()
	batchCount := 0
	total := 0
	flush := func() error {
		if batchCount == 0 {
			return nil
		}
		if err := writer.Batch(batch); err != nil {
			return err
		}
		batch = bluge.NewBatch()
		batchCount = 0
		return nil
	}
	for scanner.Scan() {
		var record sourceRecord
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			writer.Close()
			return fmt.Errorf("decode source line %d: %w", total+1, err)
		}
		// Term positions on the text fields: a phrase query needs to know which
		// terms are adjacent, and without them `"quoted phrase"` matches nothing
		// while the server looks healthy.
		document := bluge.NewDocument(strconv.Itoa(record.ID)).
			AddField(bluge.NewTextField("title", record.Title).StoreValue().SearchTermPositions()).
			AddField(bluge.NewTextField("body", record.Body).SearchTermPositions()).
			AddField(bluge.NewKeywordField("url", record.URL).StoreValue()).
			AddField(bluge.NewTextField("summary", record.Summary).StoreValue().SearchTermPositions()).
			AddField(bluge.NewKeywordField("date_text", record.Date).StoreValue()).
			AddField(bluge.NewKeywordField("sortdate", record.Date).Sortable()).
			AddField(bluge.NewStoredOnlyField("reading", []byte(strconv.Itoa(record.ReadingTime))))
		if parsed, err := time.Parse(time.RFC3339, record.Date); err == nil {
			document.AddField(bluge.NewDateTimeField("date", parsed))
		}
		// category and tag are keyword fields: the grammar matches them exactly,
		// so they must not be tokenised or stemmed. Stored as well as indexed,
		// because a result card shows them.
		if category := strings.TrimSpace(record.Category); category != "" {
			document.AddField(bluge.NewKeywordField("category", category).StoreValue())
		}
		// Indexed, not stored. Lowercased because `tag:` is matched exactly and
		// the grammar lowercases its side too.
		for _, tag := range record.Tags {
			if tag = strings.TrimSpace(strings.ToLower(tag)); tag != "" {
				document.AddField(bluge.NewKeywordField("tag", tag))
			}
		}
		// Emoji as keywords, because the analyser drops them from the text
		// fields entirely. Title as well as body: a tweet's own text is the
		// title here, and that is where most of them are.
		for _, symbol := range emojiSymbols(record.Title + " " + record.Body) {
			document.AddField(bluge.NewKeywordField("emoji", symbol))
		}
		// Stored separately, and capped: a card has room for a few tags, and a
		// note that writes thirty should not put all of them on one.
		if display := displayTags(record); display != "" {
			document.AddField(bluge.NewStoredOnlyField("tags_display", []byte(display)))
		}
		batch.Update(document.ID(), document)
		batchCount++
		total++
		if batchCount >= 500 {
			if err := flush(); err != nil {
				writer.Close()
				return err
			}
		}
		if total%10000 == 0 {
			log.Printf("indexed %d notes", total)
		}
	}
	if err := scanner.Err(); err != nil {
		writer.Close()
		return err
	}
	if err := flush(); err != nil {
		writer.Close()
		return err
	}
	if err := writer.Close(); err != nil {
		return err
	}
	stamp, _ := json.Marshal(indexStamp{SourceSize: info.Size(), SourceModUnix: info.ModTime().UnixNano()})
	old := indexDir + ".old"
	_ = os.RemoveAll(old)
	if _, err := os.Stat(indexDir); err == nil {
		if err := os.Rename(indexDir, old); err != nil {
			return err
		}
	}
	if err := os.Rename(temporary, indexDir); err != nil {
		_ = os.Rename(old, indexDir)
		return err
	}
	_ = os.RemoveAll(old)
	if err := os.WriteFile(indexDir+".stamp.json", append(stamp, '\n'), 0o644); err != nil {
		return err
	}
	log.Printf("indexed %d notes", total)
	return nil
}

// displayTags joins the first few of a note's tags for its result card,
// tab-separated because a tag cannot contain a tab.
func displayTags(record sourceRecord) string {
	kept := make([]string, 0, len(record.Tags))
	for _, tag := range record.Tags {
		if tag = strings.TrimSpace(tag); tag != "" {
			kept = append(kept, tag)
		}
		if len(kept) >= maxDisplayTags {
			break
		}
	}
	return strings.Join(kept, "\t")
}

// emojiSymbols returns the distinct emoji in a string, in order of first
// appearance.
//
// The standard analyser produces no term at all for an emoji — `😃` yields
// nothing and `happy 😃 day` yields [happy day] — so an emoji is neither
// indexed nor searchable through the text fields, and an emoji query has
// nothing to match with. They are indexed as keywords instead, which is the
// same shape `tag` uses.
//
// Rune by rune, so a joined sequence such as 👨‍👩‍👧 is found by any of its
// parts. Zero-width joiners, variation selectors and skin-tone modifiers are
// not symbols in their own right and are skipped, which is what makes 👍🏽 and
// 👍 the same search.
func emojiSymbols(text string) []string {
	var out []string
	seen := make(map[rune]bool)
	for _, r := range text {
		// Symbol-other, above the punctuation blocks: emoji live there, while
		// © and ® sit below it and are ordinary characters in prose.
		if r < 0x2000 || !unicode.Is(unicode.So, r) || seen[r] {
			continue
		}
		seen[r] = true
		out = append(out, string(r))
	}
	return out
}

// isEmojiTerm reports whether a query term is made only of emoji, which is when
// it should be matched against the keyword field rather than the text fields.
func isEmojiTerm(term string) bool {
	found := false
	for _, r := range term {
		if r < 0x2000 || !unicode.Is(unicode.So, r) {
			// Joiners and modifiers may appear between emoji without making the
			// term something other than emoji.
			if r == 0x200D || r == 0xFE0F || unicode.Is(unicode.Sk, r) {
				continue
			}
			return false
		}
		found = true
	}
	return found
}
