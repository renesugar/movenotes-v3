// Development-only oracle for the pinned Notrios normalizeMediaType rule.
// Feed the committed semantic-mime-vectors.json to reproduce its output.
package main

import (
	"encoding/json"
	"mime"
	"os"
	"strings"
)

type vector struct {
	Input      string `json:"input"`
	Accepted   bool   `json:"accepted"`
	Normalized string `json:"normalized"`
}

func main() {
	var cases []vector
	if err := json.NewDecoder(os.Stdin).Decode(&cases); err != nil {
		panic(err)
	}
	for i := range cases {
		base, params, err := mime.ParseMediaType(cases[i].Input)
		cases[i].Accepted = err == nil && base != "" && len(cases[i].Input) <= 255
		cases[i].Normalized = ""
		if cases[i].Accepted {
			cases[i].Normalized = mime.FormatMediaType(strings.ToLower(base), params)
		}
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(cases); err != nil {
		panic(err)
	}
}
