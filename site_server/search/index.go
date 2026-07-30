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
		for _, tag := range record.Tags {
			if tag = strings.TrimSpace(strings.ToLower(tag)); tag != "" {
				document.AddField(bluge.NewKeywordField("tag", tag).StoreValue())
			}
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
