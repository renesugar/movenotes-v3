// Development-only standard-library oracle for manifest serialization vectors.
// Structs copied verbatim from Notrios bdecfeda00e582d5aa6170d15b37ba27c9656f1d:
// internal/archivev2/{format,index}.go. Keep field order and JSON tags intact.
// This oracle computes semantic digests; it does not admit or verify archives.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

type Manifest struct {
	Format        string           `json:"format"`
	Version       int              `json:"version"`
	CommitSHA256  string           `json:"commit_sha256,omitempty"`
	Snapshot      SnapshotMetadata `json:"snapshot"`
	Compatibility Compatibility    `json:"compatibility"`
	Index         []IndexObject    `json:"index"`
	Totals        ObjectTotals     `json:"totals"`
	Counts        Counts           `json:"counts"`
}

type SnapshotMetadata struct {
	ID                      string   `json:"id"`
	CreatedAt               string   `json:"created_at"`
	Target                  string   `json:"target"`
	DatabaseID              string   `json:"database_id"`
	SourceReplicaID         string   `json:"source_replica_id"`
	Consistency             string   `json:"consistency"`
	CollectionIDs           []string `json:"collection_ids"`
	SelectionManifestSHA256 string   `json:"selection_manifest_sha256"`
}

type Compatibility struct {
	MinimumReaderVersion int      `json:"minimum_reader_version"`
	SourceSchemaVersion  int      `json:"source_schema_version"`
	MinimumSchemaVersion int      `json:"minimum_schema_version"`
	MaximumSchemaVersion int      `json:"maximum_schema_version"`
	RequiredCapabilities []string `json:"required_capabilities"`
	OptionalCapabilities []string `json:"optional_capabilities"`
}

type Counts struct {
	Collections       int `json:"collections"`
	Notebooks         int `json:"notebooks"`
	SearchNotebooks   int `json:"search_notebooks"`
	Tags              int `json:"tags"`
	Documents         int `json:"documents"`
	Revisions         int `json:"revisions"`
	DocumentTags      int `json:"document_tags"`
	Resources         int `json:"resources"`
	DocumentResources int `json:"document_resources"`
	Links             int `json:"links"`
	Provenance        int `json:"provenance"`
	SourceBundles     int `json:"source_bundles"`
}

type IndexObject struct {
	SHA256    string         `json:"sha256"`
	SizeBytes int64          `json:"size_bytes"`
	Entries   int            `json:"entries"`
	MediaType string         `json:"media_type"`
	Location  ObjectLocation `json:"location"`
}

type ObjectLocation struct {
	Layout     string `json:"layout"`
	Path       string `json:"path,omitempty"`
	PackSHA256 string `json:"pack_sha256,omitempty"`
	Offset     int64  `json:"offset,omitempty"`
	Length     int64  `json:"length,omitempty"`
}

type ObjectTotals struct {
	Objects      int   `json:"objects"`
	Bytes        int64 `json:"bytes"`
	RecordChunks int   `json:"record_chunks"`
	Blobs        int   `json:"blobs"`
	Packs        int   `json:"packs,omitempty"`
}

type vector struct {
	Name      string          `json:"name"`
	Manifest  json.RawMessage `json:"manifest"`
	Canonical string          `json:"canonical_utf8"`
	SHA256    string          `json:"sha256"`
}

func main() {
	var cases []vector
	if err := json.NewDecoder(os.Stdin).Decode(&cases); err != nil {
		panic(err)
	}
	for i := range cases {
		var manifest Manifest
		if err := json.Unmarshal(cases[i].Manifest, &manifest); err != nil {
			panic(err)
		}
		manifest.CommitSHA256 = ""
		raw, err := json.Marshal(manifest)
		if err != nil {
			panic(err)
		}
		hash := sha256.Sum256(raw)
		cases[i].Canonical = string(raw)
		cases[i].SHA256 = hex.EncodeToString(hash[:])
	}
	out, err := json.MarshalIndent(cases, "", "  ")
	if err != nil {
		panic(err)
	}
	fmt.Println(string(out))
}
