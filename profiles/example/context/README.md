# Your context

Put your MD files here: brand book, glossary, metric definitions, "how we like it". `/to-tableau` and `dashboard-designer` read them before writing the spec: a glossary changes labels, a metric rule changes calcs. They cite the file in their report.

Files from `context_dirs` in `profile.yaml` are read after these. Only `*.md` in the folder itself, about 40K tokens in total; the report lists what did not fit. This README is not read.
