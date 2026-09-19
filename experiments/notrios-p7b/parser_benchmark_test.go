package markdownlinks

import (
	"strings"
	"testing"
)

func BenchmarkExtractLineLayouts(b *testing.B) {
	cases := map[string]string{
		"manylinks":      strings.Repeat("[link](target) ", 500),
		"manylines":      strings.Repeat("line [link](target)\n", 500),
		"nolinks":        strings.Repeat("ordinary unicode αβγ text\n", 500),
		"singlelongline": strings.Repeat("x", 20000) + " [link](target)",
	}
	for name, body := range cases {
		b.Run(name, func(b *testing.B) {
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				_ = Extract(body)
			}
		})
	}
}
