// Development-only Go syntax oracle for blob descriptor MIME hints.
// Mirrors the parse/error/length gate in the pinned Notrios normalizeMediaType;
// semantic normalization/equality of record references is a separate phase.
package main

import (
	"encoding/json"
	"mime"
	"os"
)

type vector struct {
	Input    string `json:"input"`
	Accepted bool   `json:"accepted"`
}

func main() {
	var cases []vector
	if err := json.NewDecoder(os.Stdin).Decode(&cases); err != nil {
		panic(err)
	}
	for i := range cases {
		base, _, err := mime.ParseMediaType(cases[i].Input)
		cases[i].Accepted = err == nil && base != "" && len(cases[i].Input) <= 255
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(cases); err != nil {
		panic(err)
	}
}
