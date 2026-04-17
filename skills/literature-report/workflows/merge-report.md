# Merge New Findings into an Existing Report

Use when the user has an existing literature report and wants to incorporate new papers or updated findings.

<process>

## Step 1: Read the existing report

Read the report file to understand:
- Current structure (sections, headings)
- Papers already cited
- The narrative arc and argument
- Citation format (inline `[@key]`, footnotes, or informal)

## Step 2: Obtain new papers

Determine the source of new papers. This may require chaining with another workflow:

- **New search needed** → Follow `workflows/find-and-report.md` steps 1–4 to get a results file, then return here.
- **User provided a results file** → Use it directly.
- **User has papers in another form** → Follow `workflows/convert-and-report.md` steps 1–3 to create a results file, then return here.

## Step 3: Generate a draft report from new papers

```bash
asta literature report \
  -i .asta/literature/find/YYYY-MM-DD-new-topic-slug.json \
  -o .asta/literature/report/YYYY-MM-DD-new-topic-slug.md
```

Read the generated draft to understand what new content is available.

## Step 4: Identify what to merge

Compare the new draft against the existing report:
- **New themes** not covered in the existing report → add as new sections or subsections
- **Supporting evidence** for existing claims → weave into existing sections with new citations
- **Contradictory findings** → add as counterpoints or discussion within relevant sections
- **Duplicate coverage** → skip papers already represented

## Step 5: Merge into the existing report

Edit the existing report directly. Preserve the original structure and voice. For each addition:

1. Place new content in the most relevant existing section, or create a new section if the theme is distinct.
2. Integrate citations naturally into the narrative — don't just append a list.
3. Update any summary or conclusion sections to reflect the expanded evidence base.
4. If using a `.bib` file, add new BibTeX entries following `references/citation-conventions.md`.

## Step 6: Verify

- Read the merged report end-to-end to check for coherence.
- Ensure no duplicate citations or contradictory statements.
- Confirm section flow still makes sense with the additions.
- If using formal citations, use the **Preview** skill to verify all `[@key]` references resolve.

</process>

<success_criteria>
- Existing report structure and voice are preserved
- New findings are integrated contextually, not just appended
- No duplicate papers or contradictory unsupported claims
- Citations are consistent with the existing format
</success_criteria>
