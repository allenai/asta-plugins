#!/usr/bin/env python3
r"""The diff engine behind the "What changed" page.

A reviewer reads an edit the way GitHub and VS Code draw one: the edited
paragraph, row or line is one place on the page, and inside it only the changed
words are marked. This file does that for the rendered pages of a workspace and
for any text a page of its own wants to compare.

Pure standard library. what-changed.py loads this file from its own directory;
deck-review.py loads it for the phrase rule; a page outside the workspace loads
it alone (see "Use from a page outside the workspace").

Scripts: What changed runs only its own scripts and libraries pinned with
integrity hashes (MathJax in row 9, Mermaid in row 11), never one from a compared
site: the report is published on the repo's Pages origin, where nothing a pull
request ships may run.

What is compared, how it is drawn, and why, for each kind of content a scientist
puts in a workspace. "Page" is the rendered `<main>` of a site page, not the
`.qmd`: the reviewer sees what a reader will. Test names are in
tests/test_what_changed.py unless the row says otherwise.

Each kind of content is one entry of `KINDS`, below in this file: how it is
recognised on a rendered page (tags and class), its role to the aligner, what
the sanitizer keeps of it (tags and attributes), and, for a kind compared whole
(a unit), what counts as a change and how the old and the new are drawn. A row
here names its entries as `entry`. Each kind of output (a site page, a slide
deck, a LaTeX paper, a data file, a page made by script) is one entry of
`OUTPUT_KINDS` in what-changed.py, with its comparer.

 1. Prose (paragraphs, headings)
    entry     `paragraph`, `heading`, `formatting`; output `site page`
    compared  the rendered page, a paragraph or heading being one block
    drawn     an edited block once, on the page's own background, with no tint:
              removed words struck on red right before the added ones on
              green, a changed phrase one mark; a whole added or removed block
              light green or light red; a heading's level is not compared
    why       the edit is a place in the text, so the paragraph is not painted
              over for one changed word
    tests     test_edited_block_is_one_copy_with_the_removed_word_before_the_added_one
              test_phrase_replaced_word_for_word_is_one_mark_on_each_side
              test_edited_paragraph_is_drawn_once_with_removed_before_added
              test_a_rewritten_paragraph_is_still_one_copy_with_both_phrases_marked
              test_whole_added_and_removed_blocks_keep_their_light_shade
              test_paragraph_split_in_two_keeps_two_paragraphs
              test_heading_level_change_with_the_same_text_pairs_and_shows_no_change
              test_heading_level_change_with_an_edit_diffs_the_words
              test_formatting_only_change_marks_the_new_tag_not_the_words
              test_formatting_taken_away_alone_shows_nothing
              test_edited_block_keeps_the_formatting_it_has
              test_markup_that_does_not_nest_still_gets_the_word_diff
 2. Lists
    entry     `list`, `list item`
    compared  the rendered page, an item being a block that holds its nested list
    drawn     as prose; an edited item draws its nested list inside itself; an
              item going loose or tight (`<li>x</li>` and `<li><p>x</p></li>`)
              is no change
    why       a list that only changes how it is written is the same list
    tests     test_list_item_removed_from_a_nested_list_is_one_removed_item
              test_edited_item_draws_its_nested_list_in_the_same_item
              test_edit_in_a_nested_item_leaves_the_outer_item_unmarked
              test_loose_item_edited_to_tight_pairs_and_diffs_its_words
              test_tight_item_edited_to_loose_pairs_and_diffs_its_words
              test_loose_item_keeps_its_nested_list_when_it_goes_tight
              test_list_that_only_goes_tight_or_loose_shows_no_change
 3. Callouts (and any other `div`)
    entry     `block`; `authored edit mark` (an `<ins>` or `<del>` the author wrote:
              a container, never one of ours)
    compared  the rendered page; a `div` or `section` is a container
    drawn     aligned child by child and never marked itself, so the words,
              lists and tables inside are drawn as in rows 1, 2 and 5; a
              paragraph wrapped in, or taken out of, a new `div` still pairs with
              its old self
    why       a callout's box is the site's styling, its content is the edit
    tests     test_paragraph_wrapped_in_a_new_div_pairs_with_its_old_self
              test_wrapped_paragraph_with_an_edit_diffs_the_words_inside_the_wrapper
 4. Footnotes
    entry     `list`, `list item`, `link`
    compared  the rendered page: the note list and the reference links
    drawn     as lists (row 2) and links (row 14); ids such as `fn1` are not
              compared
    why       a renumbered or re-rendered id is render noise
    tests     no footnote test; the id rule is shown by
              test_a_renamed_inline_id_alone_is_not_a_change and
              test_removed_block_keeps_its_tags_and_drops_its_ids
 5. Tables written by hand
    entry     `table`, `table row`
    compared  the rendered page, row by row (`tr` is one block) and cell by cell
    drawn     an edited row stays one row with its changed words marked; an
              added or removed row light green or red; a cell only one side has
              leaves a gap of its width, empty or not, so values stay under
              their headers; with a header row, the columns are matched once
              from the headers and every row's cells follow them (an unchanged
              row, and a wholly added or removed row or tbody, too, with an
              empty cell for a column its side lacks), so an edited value stays
              in its column; a table that only changes its alignment is no
              change
    why       a swapped or inserted row must not spill words into its neighbour,
              nor an added column shift the values after it
    tests     test_row_inserted_between_similar_rows_is_one_added_row
              test_two_rows_swapped_never_put_a_removed_rows_words_in_its_neighbour
              test_column_added_marks_only_the_new_cells
              test_edited_cell_beside_an_added_column_is_one_row_with_the_new_cell_shaded
              test_edited_number_beside_an_added_column_stays_under_its_header
              test_edited_number_beside_a_removed_column_stays_under_its_header
              test_unchanged_row_is_drawn_under_the_new_headers_when_a_column_moved
              test_unchanged_tbody_is_drawn_under_the_new_headers_when_a_column_moved
              test_removed_row_keeps_its_values_under_their_headers_beside_an_added_column
              test_added_row_keeps_its_values_under_their_headers_beside_a_removed_column
              test_removed_tbody_keeps_its_values_under_their_headers_beside_an_added_column
              test_table_only_realigned_is_not_a_change
              test_edited_table_row_is_one_row_inside_its_table
              test_a_row_only_one_side_has_keeps_its_light_shade_in_its_cells
              test_removed_empty_cell_keeps_the_values_under_their_headers
              test_removed_empty_cell_keeps_its_colspan
              test_an_empty_cell_only_one_side_has_stays_in_the_one_row
              test_block_edit_in_a_cell_paragraph_is_marked_inside_its_one_row
 6. Tables generated by code (kable, pandas, a notebook cell)
    entry     `table`, `table row`
    compared  the rendered page, as row 5; a page whose output comes from
              running script is row 12
    drawn     as row 5, with the work bound: a long page of identical rows
              aligns them in runs, and a stretch of too many blocks is not paired
    why       a regenerated table of thousands of rows must stay responsive
    tests     test_small_edit_on_thousands_of_repeated_blocks_is_fast
              test_many_similar_edited_blocks_are_paired_without_cubic_work
              test_repeated_blocks_within_the_bound_still_align_exactly
              test_edits_at_the_ends_of_a_long_page_do_not_cost_the_middle
              test_one_more_repeated_block_is_one_insertion_not_a_rewrite
              test_run_compressed_alignment_tiles_both_lists
              test_large_repetitive_page_comparison_finishes_promptly
 7. Code blocks
    entry     `code block`
    compared  the rendered `<pre><code>`, its words and its whitespace exactly
              (indentation, line breaks, blank lines); the source file is not
              read; what-changed.py does not treat a page whose only change is
              spacing in a code block as unchanged
    drawn     as prose: changed words marked inside the block (a changed line
              is its changed words, not an old line above a new one), changed
              whitespace marked the same way, a block added or removed light
              green or red
    why       the page is what a reader sees, and in code whitespace is
              meaning; the two-row line view belongs to source text (row 18)
    tests     test_whitespace_inside_a_code_block_is_a_change_shown_exactly
              test_whitespace_outside_code_is_still_not_a_change
              test_phrase_changed_inside_code_is_one_mark_on_each_side
              test_page_whose_only_change_is_code_whitespace_is_shown
 8. Values computed inline (`` `{python} x` ``)
    entry     `inline text`
    compared  the rendered text of the page
    drawn     as prose: the old value struck, the new one added
    why       the value is text on the page once rendered
    tests     none for computed values; the word marks are row 1's
 9. Equations
    entry     `equation`
    compared  the TeX between `\( \)` or `\[ \]`, as one unit; ids on it are
              not compared (the new page's fragment, with its id, is drawn)
    drawn     typeset as on the page and compared whole, never marked inside:
              a display equation framed, never filled (the old in a thin red
              frame labelled "Before", the new in a thin green one labelled
              "After", on the page's own background, old above new), an inline
              one old then new in its line (in the darker word shade, as
              changed words); an equation beside
              an edited word is left alone. MathJax 3.2.2 and its `ui/safe`
              component, each pinned from cdn.jsdelivr.net with its integrity
              hash, are loaded only for a page that has math (`math_script`);
              safe.js keeps its own integrity hash (option b, not the loader's
              `load: ['ui/safe']`, which would load it without one): the
              config holds MathJax's `ready`, and the document is built by
              `defaultReady()` only after safe.js has run, so the safe handler
              is the one that builds it; the page typesets only once it is, with
              executable schemes (`javascript:`, `data:`) off and classes, ids
              and styles constrained, so TeX such as `\href{javascript:...}{x}`
              is never a live link on the Pages origin; the source view
              (`.wc-src`) is left out of typesetting
    why       a word diff of TeX reads as noise, and an equation is read whole
    tests     test_edited_inline_equation_is_old_in_red_then_new_in_green_as_whole_units
              test_a_whole_unit_is_framed_old_in_red_new_in_green_with_a_label_never_filled
              test_the_frames_follow_the_dark_palette
              test_edited_display_equation_is_compared_whole
              test_equation_touching_punctuation_changes_alone
              test_unchanged_equation_beside_an_edited_word_is_left_alone
              test_added_and_removed_equations_are_whole_units
              test_a_moved_unit_keeps_its_id_in_the_new_place
              test_equation_whose_only_change_is_its_id_is_no_change
              test_display_equation_paragraph_with_a_new_id_is_not_removed_and_added
              test_two_equations_with_the_same_tex_keep_their_own_ids
              test_mathjax_is_loaded_only_for_a_page_with_math
              test_the_source_view_is_never_typeset_and_never_calls_for_mathjax
              test_the_page_loads_mathjax_only_when_it_has_an_equation
              test_mathjax_is_typeset_with_its_safe_component_so_a_link_in_tex_cannot_run
              test_mathjax_builds_its_document_only_after_the_safe_component_has_run
              test_a_build_with_a_link_in_tex_typesets_it_with_the_safe_component
10. Figures and plots (one regenerated under the same file name)
    entry     `figure`
    compared  the bytes of the file each `<img>` names, on both sites, and its
              `src`: an image given another `src` is another figure
    drawn     a figure whose bytes or `src` differ shows its old and new side by side,
              as GitHub's image diff does, never marked inside: the old one in
              a thin red frame labelled "Before", the new one in a thin green
              frame labelled "After", on the page's own background with no
              fill, and no band behind the images or fading on them (the frame
              is row 9's); the old one is drawn from the
              old site's file whenever the new site does not serve those bytes
              under its name (also when its alt or width changed, or the figure
              was removed; the sanitizer keeps no srcset, sizes or `<picture>`
              source, which a browser would take over src), and a file too
              large to inline is said to be unavailable, never drawn as the
              new one; unchanged bytes are no change; a file nobody can read is
              not called changed. A pair whose image is wider at its natural
              size (its width attribute, else the file's own width) than half
              the column is drawn old above new at that size, up to the full
              column, so that it stays readable; a narrower pair stays side by
              side (`pair_script`; the same rule at 390px)
    why       a regenerated plot has the same name and the same page HTML
    tests     test_regenerated_figure_shows_before_and_after
              test_regenerated_figure_with_a_new_alt_still_shows_the_old_bytes_as_removed
              test_removed_figure_only_the_old_site_has_shows_its_old_bytes
              test_old_figure_drawn_from_its_old_bytes_has_no_srcset_sizes_or_picture_source
              test_removed_figure_with_a_srcset_drops_it_too
              test_old_figure_that_cannot_be_inlined_is_said_so_not_shown_as_the_new_one
              test_removed_figure_with_the_same_bytes_on_both_sites_keeps_its_name
              test_figure_with_the_same_bytes_is_no_change
              test_an_image_whose_src_changed_is_drawn_before_and_after
              test_a_page_whose_image_has_a_new_src_shows_the_old_file_beside_the_new
              test_image_with_no_known_digest_is_not_called_changed
              test_regenerated_figure_inside_a_quarto_figure_block
              test_page_with_a_regenerated_figure_is_shown_though_its_html_is_the_same
              test_page_whose_figure_file_is_unchanged_is_not_shown
              test_site_images_stay_inside_the_site_root
              test_changed_figure_is_markup_for_old_and_new_side_by_side
              test_a_figure_pair_is_still_old_and_new_side_by_side_when_framed
              test_a_unit_that_is_not_framed_is_shaded_like_any_other_change
11. Diagrams (Graphviz, Mermaid, TikZ, any inline drawing)
    entry     `inline svg`, `diagram text`
    compared  a diagram written to an image file is row 10. A Graphviz cell
              (`{dot}`) arrives in the rendered page as an inline `<svg>`,
              compared whole by its safe markup, ids aside. A Mermaid cell
              arrives as `<pre class="mermaid">` holding the diagram's text,
              which the site draws with script at view time; it is compared
              whole by that text
    drawn     a changed drawing old and new side by side, each framed as in row
              10, never marked inside (its labels are not marked as words); one wider at its natural
              size (its width, else its viewBox; a drawn Mermaid diagram's
              max-width) than half the column is drawn old above new at that
              size, up to the full column, a narrower one side by side, the
              same at 390px (`pair_script`, run again once Mermaid has drawn).
              A changed Mermaid diagram the same, drawn: What changed's page loads
              Mermaid 11.12.0 (the version Quarto 1.9 ships, so a drawing matches
              the site's), pinned from cdn.jsdelivr.net with its integrity hash,
              only for a page that has a changed Mermaid diagram
              (`mermaid_script`). A script a compared site ships or names is never
              loaded, whatever its name or place: the file is a pull request's to
              write. It draws the old and new text of each `.wc-unit` pair with
              it, with
              `securityLevel: 'strict'` (labels cannot carry HTML, links or
              script; `%%{init}%%` cannot lower it or add CSS) and
              `startOnLoad` off, so that only those pairs are drawn; the drawn
              SVG is then scrubbed again (no script, no event handler, no
              `javascript:` or `data:` link) before it joins the page. This is
              safe enough because the script is the pinned release, strict
              mode is Mermaid's own sanitizer, and it runs on What changed's
              page only, never on the page being compared. With no network (the
              script does not load), or a diagram Mermaid cannot draw, the diagram
              text stays, wrapped. The source view is left as it is: it shows
              the changed line. A drawing is kept only as a safe subset: shapes,
              text and paint (a `style` of paint properties), no script, no
              foreignObject, no event handler, no external reference (`href`,
              `url()` however it is spelled, `use`, `image`), no ids; an unknown element in it goes
              with its content. Not handled: a diagram a script has already
              drawn into the page's HTML as an `<svg>` with `foreignObject`
              labels (Mermaid saved after view) loses those labels
    why       a vector drawing has no words to mark, and a reader looks for what
              the drawing was and is
    tests     test_a_changed_inline_svg_is_drawn_old_and_new_never_marked_inside
              test_an_unchanged_inline_svg_is_no_change_and_one_with_other_ids_neither
              test_a_whole_added_or_removed_drawing_is_drawn_whole
              test_an_inline_svg_keeps_only_a_safe_subset
              test_a_changed_mermaid_diagram_is_its_text_old_and_new
              test_a_page_with_a_figure_pair_loads_the_pair_layout_script_once
              test_a_stacked_pair_is_old_above_new_at_its_natural_size
              (tests/dom/test_what_changed_pairs_dom.mjs: the pair layout, with stand-in widths)
              test_a_page_with_a_changed_diagram_cell_shows_old_and_new_not_a_card
              test_a_drawing_only_cell_with_other_classes_is_still_a_drawing
              test_a_page_with_a_classed_drawing_cell_is_compared_not_linked
              test_the_page_loads_pinned_mermaid_only_when_it_has_a_mermaid_unit
              test_mermaid_is_initialised_strict_with_no_auto_start
              test_a_site_with_its_own_mermaid_file_never_has_it_loaded
              test_a_script_in_a_comment_or_named_by_a_page_is_never_emitted
              test_hostile_mermaid_labels_are_inert_by_config_and_by_scrub
              (tests/dom/test_what_changed_dom.mjs: the drawing script, with a stand-in Mermaid)
12. Interactive outputs (Plotly, widgets, Observable, a bespoke report)
    entry     output `page made by script` (what-changed.py)
    compared  not by this file: what-changed.py finds a page whose content is
              made by running script and does not word-diff it; a Quarto cell
              whose whole output is a drawing (Graphviz's inline svg, Mermaid's
              text) is not such output, it is row 11
    drawn     a card with a link to the full rendered page, for new, removed and
              changed alike; a changed data payload is reported even when the
              static text is the same
    why       such a page re-renders to markup that a word diff lights up as
              change, and stripping its script leaves an empty shell
    tests     test_computed_page_is_linked_not_word_diffed_or_embedded
              test_computed_page_data_change_is_reported_even_when_static_text_is_same
              test_new_self_contained_page_is_linked_and_carries_no_foreign_script
              test_two_self_contained_pages_do_not_collide
              test_has_computed_output_detects_widgets_and_ignores_prose
              test_a_cell_whose_output_is_a_drawing_is_not_computed_output
13. Citations and the bibliography
    entry     `evidence popover`, `evidence claim`, `list` (the bibliography)
    compared  the rendered page: an evidence quote (a `span.ev` and its popover)
              as part of its claim, ids on a popover not compared, the
              bibliography as a list (row 2)
    drawn     a popover is kept whole beside its claim and never diffed inside;
              one added or removed is chipped on the claim; an excerpt's
              citation links are pointed at the full page's bibliography
              (what-changed.py)
    why       a popover is a child of its claim, and wrapping it breaks it
    tests     test_added_evidence_is_chipped_and_its_popover_stays_a_direct_child
              test_a_whole_added_claim_keeps_its_popover_and_focus
              test_unchanged_evidence_is_not_rediffed_when_prose_changes
              test_evidence_popover_whose_only_change_is_its_id_is_no_change
              test_removed_evidence_is_reported_on_the_claim
              test_single_quoted_evidence_popover_is_extracted
              test_similar_class_name_is_not_extracted_as_evidence_popover
              test_data_class_is_not_extracted_as_evidence_popover
              test_custom_span_element_does_not_affect_popover_depth
              test_citation_links_point_at_the_full_page_bibliography
14. Cross-references and links
    entry     `link`
    compared  the words of a link and its `href`; ids are not compared
    drawn     a link whose target changed keeps its place and its words are
              marked, the old target shown beside the new; a removed link keeps
              its old target; formatting alone is not a change
    why       the reader follows the link, so a retargeted link is an edit
    tests     test_link_whose_target_changed_marks_its_text_and_shows_old_and_new
              test_page_with_only_a_changed_link_target_is_shown
              test_link_whose_boundary_moves_keeps_its_old_target_in_the_one_block
              test_link_removed_from_unchanged_words_keeps_its_old_target
              test_link_whose_boundary_moved_stays_one_valid_link
              test_removed_words_keep_the_link_and_formatting_they_had
              test_removed_link_marker_text_is_readable_in_light_and_dark
              test_a_renamed_inline_id_alone_is_not_a_change
              test_prose_that_looks_like_an_id_is_still_a_change
15. Slides
    entry     output `slide deck` (what-changed.py), then as `site page`
    compared  each slide's rendered body (what-changed.py matches slides before
              and after, then diffs each pair as a page); a live deck is marked
              in the slide's own frame (deck-review.py)
    drawn     as prose, one mark per changed phrase in both; a figure redrawn
              under its name is row 10's; a slide that only moved is noted as
              reordered, not as an edit, and notes are not compared; in a
              deck's Before / after the old slide takes row 10's red frame and
              label, the new slide its green one; the unchanged slides fold
              behind row 19's strip
    why       a slide is read as a page of its own, and the two views must draw
              a phrase the same way
    tests     test_slide_whose_only_change_is_its_figure_file_is_shown
              in tests/test_deck_review.py: test_marked_slide_phrase_is_one_mark
              test_marked_slide_strikes_deletions_where_they_were
              test_live_marks_only_changed_words_outside_tags_and_scripts
              test_slide_diff_uses_the_rendered_view_and_falls_back_to_text
              test_reorder_only_omits_invisible_text_changes
              test_notes_only_change_is_not_a_visible_edit
              test_before_after_frames_the_old_slide_red_and_the_new_slide_green
              test_a_run_of_unchanged_slides_is_one_strip_named_in_slides
16. The LaTeX paper
    entry     output `LaTeX paper` (what-changed.py)
    compared  not by this file: latexdiff's PDF, built and linked by
              what-changed.py above the site's pages
    drawn     as latexdiff draws it; a paper without a diff links the clean PDF;
              the viewer's bar is the paper's title and file, then "Changes
              marked" and "Clean", then the whole-window button at the far
              right (the same in the page and in the whole window); a marked
              PDF has no note saying so; Escape leaves the whole window, the
              focus going to the bar's button so that the key reaches the page
              and not the PDF, and the reader returns to the same place in the
              paper (kept relative to its section, with scroll anchoring off
              while the PDF settles)
    why       the paper's source is not the rendered site
    tests     test_paper_diff_appears_before_quarto_changes
              test_paper_diff_reads_in_the_paper_pages_viewer
              test_paper_without_a_diff_shows_the_clean_pdf_and_no_switch
              test_a_paper_note_says_nothing_when_its_marked_pdf_says_it_all
              test_the_papers_bar_is_title_file_then_the_switch_then_the_whole_window_button
              test_the_paper_leaves_whole_window_on_escape_keeping_focus_and_the_place
              (tests/dom/test_what_changed_paper_dom.mjs: the bar's order, Escape,
              the focus, the place kept)
17. Notebooks
    entry     output `page made by script`, or `site page` for its prose
    compared  the rendered page of a notebook, which is row 12 when its cells
              show computed output and rows 1 to 11 for its prose; the `.ipynb`
              JSON is not read
    drawn     a card with a link, or as the rows above
    why       a notebook's output regenerates on every render
    tests     test_has_computed_output_detects_widgets_and_ignores_prose
18. Data files (CSV, JSON, YAML, BibTeX)
    entry     output `data file` (comparer `source_diff`); line kind `source line`
    compared  the text of the file, line by line, then the words of each paired
              line (`source_diff`); the site page does not show them, so a
              caller that has the old and new text calls it
    drawn     an edited line is two rows, the old line (light red, removed
              words darker) above the new one (light green, added words
              darker), with old and new line numbers, as GitHub's source view;
              deeper word shades in dark mode
    why       a line is the unit of such a file; not handled: a cell, a key or a
              BibTeX entry is not a unit, so a moved entry reads as removed in
              one place and added in the other
    tests     test_source_diff_numbers_lines_and_shades_like_blocks
              test_source_diff_escapes_and_keeps_indentation_and_blank_lines
              test_source_diff_of_equal_texts_has_no_marks
              test_source_diff_pairs_by_the_shared_engine_not_by_position
              test_source_lines_are_a_kind_of_the_one_element_table
              test_source_views_keep_the_old_line_above_the_new_one
              test_dark_source_words_stand_off_their_line_tint_and_keep_text_legible
19. Markdown outside the site (a README, a cases file on a review card)
    entry     as rows 1 to 11 or row 18
    compared  the HTML the page's own renderer wrote from each version
              (`diff_content`), or the Markdown text (`source_diff`)
    drawn     as rows 1 to 11 or row 18, in a fragment the page scopes under
              `.wc-scope`; long unchanged stretches fold behind one strip, in
              a list as an `li` and in a table body as a row with one cell
              across (tests/dom/test_what_changed_dom.mjs: a bullet list, an
              ordered list's numbers, a table body); the strip is tinted What
              changed's blue with blue arrows and says what it hides in a
              reader's terms, "⋯ 3 unchanged paragraphs", "⋯ 2 unchanged list
              items", "⋯ 12 unchanged lines" (the deck's "⋯ 4 unchanged slides
              (1–4)" is the same strip); a wholly added or removed block whose
              first line hangs (a reference) has its shade grown to cover that
              line (tests/dom/test_what_changed_dom.mjs)
    why       one engine draws every edit, so a review card reads like the site
    tests     test_outside_page_gets_fragments_from_both_entry_points
              test_every_style_selector_is_scoped_under_wc_scope
              test_module_imports_only_the_standard_library
              test_one_stylesheet_and_one_fold_strip_serve_both_inputs
              test_every_fold_strip_has_one_look_tinted_what_changeds_blue
              test_the_strips_names_come_from_the_table_of_kinds_in_a_readers_terms
              test_a_wholly_added_block_with_a_hanging_first_line_is_shaded_from_the_line
              test_output_ships_client_side_folding_but_keeps_full_content
              test_diff_styles_are_one_palette_of_solid_red_and_green_in_light_and_dark
20. Video (not handled)
    entry     none
    compared  not at all: the sanitizer drops `<video>` with its content (and
              `<audio>`), as the workspace's page always did; a reader sees
              nothing where a video was, whether it changed or not
    why       no example case shows it yet; it comes back with one
    tests     test_a_dropped_void_element_does_not_swallow_the_page (a video
              with its sources and tracks goes whole, and the page after it stays)

Safety. `diff_content` makes both of its sides safe before it reads them
(`sanitize_fragment`, driven by what each entry of `KINDS` keeps), so a page
outside the workspace cannot skip it; `source_diff` escapes every token. What is
kept is the table's tags and attributes, links and files that are relative,
http, https or mailto, and nothing that runs: no script, event handler, inline
style (but a drawing's paint), form, frame, plugin, `audio` or `video` (both go
with their content). Ids are dropped by
what-changed.py (which embeds many pages in one) and kept by `diff_content`
when they are plain names, as the engine compares around them; a page that
embeds several fragments drops them (`strip_ids`). Tests:
test_diff_content_called_alone_comes_out_inert,
test_source_diff_of_hostile_text_is_text,
test_the_sanitizer_keeps_what_the_table_keeps_and_nothing_else,
test_embedded_markup_is_strictly_sanitized,
test_a_dropped_void_element_does_not_swallow_the_page (what follows it stays), test_a_drawing_keeps_no_reference_outside_itself.

Adding a kind
  1. Add its entry to `KINDS`: its `name`, its `tags` and `cls`, its `role`,
     what it `keep`s, and for a unit its `unit` (a `Unit`; a subclass only if it
     needs code of its own, as `ImageUnit` and `PopoverUnit` do, with its
     `order` where its pass must run among the others). Name it in the header's
     row for its content, as `entry`. Nothing else lists the kinds: the passes
     over a page (`passes`), what is formatting or structural (`format`,
     `structural`), what the stylesheet draws as a figure (`figure`), which
     tags `ImageUnit` owns, and what a drawing-only cell holds
     (`holds_drawing`) are read from the entries.
     A `Unit`'s `compare` and `draw` are descriptions, in the header's words,
     for the reader and the tests; they do not run. The code that compares and
     draws is the unit's pass (`extract`, `whole`, `restore`).
  2. Add its test to tests/test_what_changed.py (its role, what the sanitizer
     keeps, and how a change is drawn), and name the test in its row. The tests
     of the table itself: test_a_kind_added_by_its_entry_alone_is_extracted_owned_and_restored,
     test_an_image_kind_owns_the_tags_its_entry_names,
     test_the_recognizers_are_read_from_the_entries_of_the_table.
  3. Add its case to the example workspace's sample edit
     (examples/workspace-demo.patch), so that What changed's demo shows it.
  A kind of output is an entry of `OUTPUT_KINDS` in what-changed.py with its
  comparer, named in the header the same way.

Why our own engine
  We tried `lxml.html.diff` and diff-match-patch against this engine, on the
  example's sample edit and on 10 real edits.
  * lxml broke the table's columns, marked inside the TeX of equations, dropped
    the old figure, inserted "Link: <url>" text, and drew about twice the marks
    on half of the edits.
  * diff-match-patch marked unchanged words as removed and re-added on 7 of 26
    passages.
  * Neither has any notion of kinds (an equation, a figure, a drawing, a
    table's columns), and asta-plugins is public, so adopting either would need
    Ai2 Legal's dependency review. This file is standard library only.

Colours: removed is red, added is green, in two shades each. The light shade
fills a whole added or removed block, row or line; the darker one marks only
words, and is deeper again on the words of a dark source view. Nothing else is
tinted: an edited block is on the page's own background, and a whole display
equation, figure or diagram is framed in the line colour of its side, never
filled.

The two steps
  1. Align blocks (`parse_blocks`, `_diff_children`). A page is parsed into a
     tree: every non-inline element is a block, and the words and inline tags
     between blocks form a run. Parsing makes equal what is no
     change (an item's leading `<p>x</p>` is its own words, h1-h6 are one
     tag, ids are dropped). The children of each element are aligned old to new
     on whole-block keys (`_align`, difflib with a work bound). In a stretch
     that did not align, blocks are paired the way difflib.Differ pairs lines
     (`_pair_stretch`, `_pairing`, `_similarity`): the most similar old and new
     block of the same tag, if their shared-word ratio reaches PAIR_RATIO, is one
     edited block, and the stretches before and after it are paired the same way.
     Every pair in a stretch is scored once, so PAIR_BUDGET bounds the work. The
     cells of a table follow the columns matched from its header rows
     (`_table_columns`, `_by_column`). Unpaired blocks are wholly removed or added (`_render_whole`). Each pair is
     entered, so a changed word deep in a section never replaces the section.
     What each element is to this step is its entry in KINDS (`role_of`): text
     (p, h1-h6, li, dt, dd, a source line), row (tr), unit (an equation, a
     figure, a drawing, a diagram's text: compared whole), inline
     (words and tags inside a block) or container (everything else).
  2. Mark words (`_word_parts`). The words of each pair of runs are aligned
     (`_align` again) and written with `<ins>` and `<del>` that only ever wrap
     words and inline tags, so the markup stays valid (`emit_run`, `_emit`,
     `balanced_inline`). A gap of only spaces between two changed spans joins
     them into one mark (`_join_marks`, `gap_joins_marks`).

Where things live
  Entry points      diff_content (a page), source_diff (lines of text),
                    gap_joins_marks (the one phrase rule, also used by
                    deck-review.py for slides)
  Parsing           tokenize, tag_name, is_inline_tag, is_void, parse_blocks,
                    _Node, _inline_nested, _hoist_paragraph, drop_id_attrs,
                    strip_ids
  Step 1            _align, _runs, _expand_runs, _diff_children, _steps,
                    _table_columns, _by_column, _header_cells, _pair_stretch,
                    _pairing, _similarity, _sole_child, _render_whole,
                    _edit_copies, _side_raw, _line_node
  Step 2            _word_parts, _align_key, _join_marks, emit_run, _emit,
                    balanced_inline, _mark_target, _mark_old_target, _link_gone
  The table         KINDS, Kind, role_of, unit_of, is_figure, is_structural,
                    holds_drawing; Unit, ElementUnit, PopoverUnit, ImageUnit (the
                    code a unit kind needs of its own; `passes()` lists them,
                    read from the entries)
  Kept whole        extract_units / restore_units (equations, drawings,
                    diagram text), extract_ev_popovers / restore_ev_popovers
                    (evidence popovers), stamp_images, regenerated_images,
                    SiteImages, _image_change, _old_image (files)
  Safety            sanitize_fragment, safe_url, rebase_relative_url
  Math              math_script (MathJax 3.2.2 with its safe component, for a page
                    that has an equation)
  Diagrams          mermaid_script (Mermaid 11.12.0 pinned with its integrity
                    hash, strict, for a page that has a changed Mermaid diagram)
  Figure pairs      pair_script (old above new for a pair too wide for half the
                    column), for a page that has a changed figure or drawing
  Drawing           DIFF_STYLE, FOLD_JS (folds long unchanged stretches),
                    STANDALONE_STYLE (body type for a page with no theme)

Use from a page outside the workspace
  A page of its own can build the same diff by loading this file at a pinned
  release tag (the raw file; there is no package):
      spec = importlib.util.spec_from_file_location("diff_engine", path)
      engine = importlib.util.module_from_spec(spec); spec.loader.exec_module(engine)
  * `diff_content(old_html, new_html)` and `source_diff(old_text, new_text)` are
    the public, stable entry points; `diff_content` sanitizes its own input. Each yields an HTML fragment (no <html>,
    <head> or <body>): `source_diff` returns it, `diff_content` returns
    `(fragment, changed)`, `changed` saying whether a reader would see a change.
    `diff_content` takes `images`, a callable `images(side, src)` returning a
    digest of the file an `<img>` names on the "old" or "new" site (None if
    unknown); `SiteImages(old_root, new_root)` is one over two rendered trees.
  * The page includes `DIFF_STYLE`, `STANDALONE_STYLE` (each in a <style>) and
    `FOLD_JS` (in a <script>, after the fragment; `math_script(fragment)` too
    when it has equations: it returns "" when it has none; `mermaid_script(fragment)`
    likewise for a changed Mermaid diagram (Mermaid pinned from cdn.jsdelivr.net
    with its integrity hash); `pair_script(fragment)` likewise for a changed
    figure or drawing, which sets a wide pair old above new), and puts the fragment inside
    `<div class="wc-scope wc-standalone" data-wc-fold>`: `data-wc-fold` is what
    folds long unchanged stretches of that container when the script runs. A
    container filled later is folded by `window.wcFold.fold(container)`. Every
    selector of the two styles is
    scoped under `.wc-scope`, so the page's own styles are left alone. Light and
    dark both work (`prefers-color-scheme`), and lines wrap on a 390px screen
    with no sideways scroll.
  * A page with a theme of its own leaves out `wc-standalone` (and
    `STANDALONE_STYLE`): the diff then takes the page's type, rule colour and
    muted text (Bootstrap's `--bs-secondary-color`, else a thinned copy of the
    page's own text colour, so that it reads on a dark page too). It turns dark only from `data-wc-mode="dark"` on an ancestor, so
    the page sets that attribute (on `<html>`, say) while its dark theme shows
    and removes it in light.
  * A themed page sets the diff's colours, rather than overriding its rules,
    through these variables, which are stable across releases like the entry
    points: `--wc-ins-bg` and `--wc-del-bg` (an added or removed word),
    `--wc-ins-blk` and `--wc-del-blk` (a whole added or removed block, and an
    edited block's old and new copy), `--wc-ins-line` and `--wc-del-line` (an
    added word's leading edge, a removed word's strike, the frame of a changed
    figure or equation), `--wc-changed`, `--wc-new` and `--wc-removed` (a
    page's or slide's label and edge; `--wc-changed` also the folds' strips)
    and `--wc-tag-fg` (text on a label). Set
    them on `.wc-scope` in a rule that wins over this file's: as specific and
    placed after `DIFF_STYLE` in light (`.wc-scope { … }`), and in dark at least
    `[data-wc-mode="dark"] .wc-scope { … }` (`html[data-wc-mode="dark"]
    .wc-scope` wins wherever it is placed). The marks' classes are stable too:
    `ins` and `del` (changed words), `.wc-block-added` and `.wc-block-removed`
    (a whole block), `.wc-edit-old` and `.wc-edit-new` (an edited block's two
    copies).
  * Its input is HTML as a renderer writes it (Quarto, Pandoc, a Markdown
    renderer), with `<` and `>` inside attribute values escaped, and may be
    hostile: it is made safe first. A raw `>` inside a quoted attribute value
    ends the tag early, as in the workspace's own diff.
"""

import base64
import bisect
import difflib
import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
from collections import Counter
from html.parser import HTMLParser
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

# Inline tags (INLINE_TAGS, derived from KINDS below) may live *inside* an
# <ins>/<del>; anything else is structural and closes the wrapper so we never
# nest a block element inside <ins>/<del> where its parent won't allow it (e.g.
# <ins> as a child of <ul>).

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

TOKEN_RE = re.compile(r"<[^>]+>|[^<]+")
WORD_RE = re.compile(r"\s+|[^\s]+")
TAG_NAME_RE = re.compile(r"</?\s*([a-zA-Z0-9]+)")


# One attribute of a tag (name, then a value quoted either way or not at all).
# Scanning a tag attribute by attribute keeps `id=3` inside another attribute's
# quoted value (a title, an aria-label) out of reach.
_ATTR_RE = re.compile(
    r"""(?s)\s+([^\s"'=<>/`]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?"""
)
_ANY_TAG_RE = re.compile(r"(?s)<[a-zA-Z][^>]*>")


def drop_id_attrs(tag):
    """`tag` without its `id` attribute (the one whose name is `id`)."""
    return _ATTR_RE.sub(lambda m: "" if m.group(1).lower() == "id" else m.group(0), tag)


def strip_ids(markup):
    """`markup` without the `id` attributes of its tags (its text is left as is:
    prose may say `id=3`)."""
    return _ANY_TAG_RE.sub(lambda m: drop_id_attrs(m.group(0)), markup)


def tokenize(content):
    """Split HTML into a flat list of (kind, text) tokens.

    kind is 'tag' for markup, 'word' for a non-whitespace run, 'space' for a
    whitespace run. Words/tags are what the diff aligns on; spaces ride along
    with the neighbouring op so wrapping stays tight.
    """
    tokens = []
    for chunk in TOKEN_RE.findall(content):
        if chunk.startswith("<"):
            tokens.append(("tag", chunk))
        else:
            for w in WORD_RE.findall(chunk):
                if w.isspace():
                    tokens.append(("space", w))
                    continue
                # A whole unit (an equation) is its own word, whatever text
                # touches it, so only the unit changes when it does.
                for part in UNIT_SPLIT_RE.split(w):
                    if part:
                        tokens.append(("word", part))
    return tokens


def tag_name(tok):
    m = TAG_NAME_RE.match(tok)
    return m.group(1).lower() if m else ""


def is_inline_tag(tok):
    return tag_name(tok) in INLINE_TAGS


def is_structural(tok):
    """An open tag of a kind that is structural (the table's `structural` entries:
    an evidence claim's own `<span class="ev">`), never wrapped in <ins>/<del>, so
    that its popover stays the direct child the hover CSS needs."""
    if tok.startswith("</"):
        return False
    return any(
        _names(kind, tag_name(tok), classes_of(tok))
        for kind in KINDS
        if kind.structural
    )


def balanced_inline(tokens):
    """Indices of inline tags whose matching partner is inside this same run.

    An inline pair (`<strong>`…`</strong>`) that is only *partly* inside a
    changed run — the open tag changed but its close sits in unchanged content,
    or vice versa — cannot be highlighted without producing a lone tag inside
    an <ins>/<del> (e.g. `<ins><strong></ins>`), which is invalid markup even
    if browsers recover from it. Such half-in tags are excluded here so
    emit_run treats them as structural (emitted bare / dropped) instead.
    Self-closing/void inline tags (<br>, <img>, <wbr>) are self-balanced.
    """
    balanced = set()
    stack = []
    for idx, (kind, text) in enumerate(tokens):
        if kind != "tag" or not is_inline_tag(text):
            continue
        name = tag_name(text)
        if text.startswith("</"):
            for si in range(len(stack) - 1, -1, -1):
                if stack[si][0] == name:
                    _, open_idx = stack.pop(si)
                    if not is_structural(tokens[open_idx][1]):
                        balanced.add(open_idx)
                        balanced.add(idx)
                    break
        elif text.rstrip().rstrip(">").endswith("/") or name in VOID_TAGS:
            balanced.add(idx)  # void/self-closing: needs no partner
        else:
            stack.append((name, idx))
    return balanced


def _is_format_open(tok):
    return tag_name(tok) in FORMAT_TAGS and not tok.startswith("</")


def _mark_format(tag):
    tag = _add_class(tag, "wc-fmt-changed")
    if _TITLE_RE.search(tag):
        return tag
    return re.sub(
        r"\s*/?>$", lambda m: ' title="formatting changed"' + m.group(0), tag, 1
    )


def emit_run(tokens, wrapper, images=None):
    """Render a changed run.

    wrapper is 'ins' or 'del'. Structural tags — and inline tags whose partner
    falls outside this run — close/skip the wrapper so the result stays
    well-formed:
      * ins: such tags are emitted verbatim (outside the wrapper); words and
        balanced inline tags are highlighted inside <ins>.
      * del: a fully-deleted subtree's structural tags are dropped (open+close
        both fall in the deleted run, so nesting stays balanced); deleted words
        and balanced inline tags are shown struck-through inside <del>.
    """
    return _emit(tokens, wrapper, images=images)[0]


_HREF_RE = re.compile(r"""(?is)\shref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def _link_gone(tag):
    """The mark for an old `<a href>` whose open tag the new page does not have,
    carrying its old destination (shown beside it, as a changed target is);
    "" for any other tag."""
    if tag_name(tag) != "a" or tag.startswith("</"):
        return ""
    m = _HREF_RE.search(tag)
    if not m:
        return ""
    was = html.unescape(next(g for g in m.groups() if g is not None))
    was = html.escape(was, quote=True)
    return (
        f'<span class="wc-link-was wc-link-gone" data-wc-was="{was}" '
        f'title="link removed: {was}"></span>'
    )


def _emit(tokens, wrapper, keep_tags=False, images=None):
    """emit_run, and whether it marked anything a reader sees: a word, an inline
    pair, an evidence quote. Half-in formatting tags alone (em -> strong) mark
    nothing. `keep_tags` draws the removed words of the old copy, which keeps
    every tag it had (its own nesting) and wraps only the words. `images` is
    what `diff_content` takes: a removed `<img>` is drawn from its old bytes."""
    out = []
    open_wrap = False
    marked = False
    inline_ok = balanced_inline(tokens)

    def close():
        nonlocal open_wrap
        if open_wrap:
            out.append(f"</{wrapper}>")
            open_wrap = False

    def open_():
        nonlocal open_wrap
        if not open_wrap:
            out.append(f"<{wrapper}>")
            open_wrap = True

    for idx, (kind, text) in enumerate(tokens):
        highlightable = kind == "word" or (
            kind == "tag" and is_inline_tag(text) and idx in inline_ok
        )
        if unit := unit_of(kind, text):
            # A whole unit (equation, figure, drawing, popover) is drawn by its
            # kind: as a whole, in the light shade, never in the word shade.
            close()
            out.append(unit.whole(text, wrapper, images))
            marked = True
        elif kind == "tag" and not highlightable:
            close()
            if wrapper == "ins" and _is_format_open(text):
                # Formatting put on words that were already there (em ->
                # strong): the new tag is marked, so the change shows.
                out.append(_mark_format(text))
                marked = True
            elif wrapper == "ins" or keep_tags:
                out.append(text)  # keep structure for inserted blocks
            elif gone := _link_gone(text):
                # A removed link whose words stay (its boundary moved, or it was
                # unlinked): its old target is kept, marked, where the link began.
                out.append(gone)
                marked = True
            # other deleted structural / half-in inline tags are dropped with subtree
        elif kind == "space":
            out.append(text)  # rides along whether or not a wrapper is open
        else:  # word or balanced inline tag
            open_()
            marked = True
            out.append(text)
    close()
    return "".join(out), marked


# Evidence popovers (`<span class="ev-pop">…</span>`, injected by the workspace
# evidence extension) are hover-only payloads, not prose, and word-diffing them
# broke twice on real PRs: an inserted popover landed *inside* the `<ins>`
# wrapper, so it stopped being the direct child `.ev:hover > .ev-pop` needs and
# the hover showed nothing; and evidence added to otherwise-unchanged prose was
# marked only inside that hidden popover, i.e. invisibly. So each popover is
# swapped for one opaque placeholder tag before the diff and restored after.
EV_POP_OPEN_RE = re.compile(
    r"""(?is)<span(?=\s|/|>)[^>]*?\sclass\s*=\s*(?P<quote>["'])(?P<classes>.*?)(?P=quote)[^>]*>"""
)
# `wc-evpop` is deliberately not an inline tag: emit_run then treats it as
# structural and emits it OUTSIDE any <ins>, which is what restores the
# direct-child relationship the popover CSS depends on.
EV_POP_PLACEHOLDER = '<wc-evpop data-k="%s">'
EV_POP_OP_PLACEHOLDER = '<wc-evpop data-k="%s" data-op="%s">'
EV_POP_RE = re.compile(r'<wc-evpop data-k="([0-9a-f]+)"(?: data-op="(add|del)")?>')

# An element unit (an equation, a drawing, a diagram's text; see KINDS)
# is swapped for one opaque word before the diff and restored after, like an
# evidence popover, so no mark ever lands inside it and an edited one is the old
# struck and the new added.
# A figure-like unit (a drawing, a diagram's text) is `wcfig-`: unlike
# an equation it has no words of its own, so, like an image, two blocks that
# each hold one are one edited block.
UNIT_WORD = "wcunit-%s"
FIG_WORD = "wcfig-%s"
UNIT_SPLIT_RE = re.compile(r"(wc(?:unit|fig)-[0-9a-f]{16})")
UNIT_RE = re.compile(r"wc(?:unit|fig)-([0-9a-f]{16})")
UNIT_FULL_RE = re.compile(r"wc(?:unit|fig)-[0-9a-f]{16}$")


def extract_units(content):
    """Swap every element unit for a placeholder word; return both. The key of a
    unit is its markup."""
    out, store, pos = [], {}, 0
    for m in ELEMENT_UNIT_OPEN_RE.finditer(content):
        if m.start() < pos:
            continue
        name = m.group(1).lower()
        unit = element_unit(name, m.group(0))
        end = matching_close(content, m.end(), name) if unit else None
        if end is None:
            continue
        frag = content[m.start() : end]
        key = hashlib.sha1(frag.encode("utf-8")).hexdigest()[:16]
        store[key] = frag
        out.append(content[pos : m.start()])
        out.append((FIG_WORD if unit.figure else UNIT_WORD) % key)
        pos = end
    out.append(content[pos:])
    return "".join(out), store


_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*)>")
_OLD_MARK_RE = re.compile(r"""(?is)\bclass\s*=\s*["'][^"']*\bwc-block-removed\b""")


def _in_old_copy(content, positions):
    """Whether each position (ascending) of `content` sits in the old page's
    copy: inside a `<del>` or a removed block."""
    tags = _TAG_RE.finditer(content)
    stack, out, nxt = [], [], next(tags, None)
    for pos in positions:
        while nxt is not None and nxt.end() <= pos:
            closing, name, rest = nxt.groups()
            name = name.lower()
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        del stack[i:]
                        break
            elif not (
                name in VOID_TAGS
                or name in PLACEHOLDER_TAGS  # (a placeholder has no close)
                or rest.endswith("/")
            ):
                stack.append((name, name == "del" or bool(_OLD_MARK_RE.search(rest))))
            nxt = next(tags, None)
        out.append(any(o for _, o in stack))
    return out


def _restore(pattern, content, store, draw=None):
    """Put each stored fragment back for its placeholder, so that ids stay unique.

    A fragment drawn in the old page's copy keeps no ids (the new page owns
    them); of the copies in the new page, the last keeps them.
    `draw(match, fragment, in_old_copy)` gives what replaces the placeholder."""
    found = list(pattern.finditer(content))
    where = [m.start() for m in found]
    old = dict(zip(where, _in_old_copy(content, where)))
    last = {m.group(1): m.end() for m in found if not old[m.start()]}

    def sub(m):
        frag = store.get(m.group(1))
        if frag is not None and (old[m.start()] or m.end() != last[m.group(1)]):
            frag = strip_ids(frag)
        if frag is None:
            return m.group(0)
        return draw(m, frag, old[m.start()]) if draw else frag

    return pattern.sub(sub, content)


def restore_units(content, store):
    """Put the element units back."""
    return _restore(UNIT_RE, content, store)


_SRC_RE = re.compile(r"""(?is)\ssrc\s*=\s*(["'])(.*?)\1""")
_DIGEST_RE = re.compile(r' data-wc-digest="[0-9a-f]*"')
_DIGEST_VALUE_RE = re.compile(r' data-wc-digest="([0-9a-f]*)"')


def stamp_images(content, side, images):
    """Tag each `<img>` with its file's digest, when the caller can resolve it.

    `images(side, src)` returns a digest (any hex string that is equal when the
    file's bytes are) or None; side is "old" or "new", src as written in the
    page. The stamp makes a regenerated figure's block differ from its old self;
    the diff strips it again before output.
    """
    if images is None or not _IMG_RE.search(content):
        return content

    def sub(m):
        tag = m.group(0)
        src = _SRC_RE.search(tag)
        digest = images(side, html.unescape(src.group(2))) if src else None
        if not digest:
            return tag
        return re.sub(
            r"\s*/?>$", lambda e: f' data-wc-digest="{digest}"' + e.group(0), tag, 1
        )

    return _IMG_RE.sub(sub, content)


def regenerated_images(old, new, images):
    """Sources in both bodies whose file differs: a plot redrawn under its name."""
    if images is None:
        return []
    srcs = lambda doc: {  # noqa: E731
        html.unescape(m.group(2))
        for t in _IMG_RE.findall(doc)
        for m in [_SRC_RE.search(t)]
        if m  # fmt: skip
    }
    found = []
    for src in sorted(srcs(old) & srcs(new)):
        before, after = images("old", src), images("new", src)
        if before and after and before != after:
            found.append(src)
    return found


class SiteImages:
    """`images` for `diff_content`, over the two rendered site trees.

    Called as `images(side, src)` it returns a digest of the file `src` names
    under that side's root (None for an external URL or a missing file);
    `before_url(src)` is the old file inlined as a data URI (the old site is not
    served beside the diff), None past INLINE_LIMIT bytes.
    """

    INLINE_LIMIT = 3_000_000

    def __init__(self, old_root, new_root):
        self.roots = {
            "old": os.path.realpath(old_root),
            "new": os.path.realpath(new_root),
        }
        self._digests = {}

    def _path(self, side, src):
        parts = urlsplit(src)
        if parts.scheme or parts.netloc or not parts.path:
            return None
        rel = posixpath.normpath(unquote(parts.path).lstrip("/"))
        if rel == ".." or rel.startswith("../"):
            return None
        path = os.path.realpath(os.path.join(self.roots[side], rel))
        if os.path.commonpath([self.roots[side], path]) != self.roots[side]:
            return None
        return path if os.path.isfile(path) else None

    def __call__(self, side, src):
        path = self._path(side, src)
        if path is None:
            return None
        if path not in self._digests:
            digest = hashlib.sha1()
            try:
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 16), b""):
                        digest.update(chunk)
            except OSError:
                return None
            self._digests[path] = digest.hexdigest()[:16]
        return self._digests[path]

    def before_url(self, src):
        path = self._path("old", src)
        if path is None or os.path.getsize(path) > self.INLINE_LIMIT:
            return None
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        return f"data:{mime};base64,{data}"


_ALT_RE = re.compile(r"""(?is)\salt\s*=\s*(["'])(.*?)\1""")


def _old_image(tag, images):
    """An old page's `<img>` as the removed side draws it. The diff is served
    from the new site, so a file the new site does not serve under that name
    (other bytes, or gone) is drawn from its old bytes, inlined; if those cannot
    be had (past INLINE_LIMIT), a note says so: the new file is never shown as
    the old one."""
    digest, src = _DIGEST_VALUE_RE.search(tag), _SRC_RE.search(tag)
    if images is None or not digest or not src:
        return tag
    name = html.unescape(src.group(2))
    if images("new", name) == digest.group(1):
        return tag
    if url := getattr(images, "before_url", lambda name: None)(name):
        # (The sanitizer keeps no srcset or sizes, which a browser would take
        # over src, and no picture source: nothing shows the new file here.)
        return _SRC_RE.sub(
            lambda m: f' src="{html.escape(url, quote=True)}"', tag, count=1
        )
    alt = _ALT_RE.search(tag)
    return (
        '<span class="wc-img-unavailable">old image not shown (too large to '
        f"show beside the new page){': ' + alt.group(2) if alt else ''}</span>"
    )


def _image_change(old_tok, new_tok, images):
    """Before and after of an image whose file changed under the same name, as
    (old, new): each a whole unit, the old one for the old side, the new one
    for the new side."""
    if not ImageUnit.owns("tag", old_tok):
        return None
    od, nd = _DIGEST_VALUE_RE.search(old_tok), _DIGEST_VALUE_RE.search(new_tok)
    new_bare = _DIGEST_RE.sub("", new_tok)
    same = _DIGEST_RE.sub("", old_tok) == drop_id_attrs(new_bare)  # (ids are not it)
    if not (od and nd and od.group(1) != nd.group(1) and same):
        return None
    return (
        f'<del class="wc-unit">{_old_image(old_tok, images)}</del>',
        f'<ins class="wc-unit">{new_bare}</ins>',
    )


EV_CHIP = {
    "add": '<span class="wc-ev-chip wc-ev-add">evidence added</span>',
    "del": '<span class="wc-ev-chip wc-ev-del">evidence removed</span>',
}


def matching_close(content, start, name):
    """Index just past the `</name>` that closes the element open at `start`."""
    pat = re.compile(rf"(?is)<(/?){re.escape(name)}(?=\s|/|>)[^>]*>")
    depth, pos = 1, start
    while True:
        m = pat.search(content, pos)
        if not m:
            return None
        pos = m.end()
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()


def extract_ev_popovers(content):
    """Swap every evidence popover subtree for a placeholder; return both."""
    out, store, pos = [], {}, 0
    for m in EV_POP_OPEN_RE.finditer(content):
        if "ev-pop" not in m.group("classes").split():
            continue
        if m.start() < pos:
            continue
        end = matching_close(content, m.end(), "span")
        if end is None:
            continue
        frag = content[m.start() : end]
        key = hashlib.sha1(frag.encode("utf-8")).hexdigest()[:16]
        store[key] = frag
        out.append(content[pos : m.start()])
        out.append(EV_POP_PLACEHOLDER % key)
        pos = end
    out.append(content[pos:])
    return "".join(out), store


def _same_but_ids(old, new, old_store, new_store, pattern):
    """`old` with each placeholder whose fragment differs from one of `new`'s
    only by ids named as that one (the i-th such in `old` as the i-th in `new`),
    so that a re-rendered id is no change; the new page's fragment is what
    is drawn."""
    by_bare = {}
    for m in pattern.finditer(new):
        by_bare.setdefault(strip_ids(new_store[m.group(1)]), []).append(m.group(1))
    seen = Counter()

    def sub(m):
        bare = strip_ids(old_store[m.group(1)])
        at, seen[bare] = seen[bare], seen[bare] + 1
        keys = by_bare.get(bare, ())
        return (
            m.group(0).replace(m.group(1), keys[at]) if at < len(keys) else m.group(0)
        )

    return pattern.sub(sub, old)


def restore_ev_popovers(content, store):
    """Put the popovers back, chipping the ones this change added or removed."""

    def draw(m, frag, in_old_copy):
        chip = EV_CHIP.get(m.group(2), "")
        if m.group(2) == "del":
            return chip  # the quote itself is gone; only the fact of it remains
        return chip + frag

    return _restore(EV_POP_RE, content, store, draw)


BLOCK_CLASS = {"ins": "wc-block-added", "del": "wc-block-removed"}

HEADING_RE = re.compile(r"h[1-6]$")
_CLASS_RE = re.compile(r"""(?is)(\sclass\s*=\s*)(["'])(.*?)\2""")


class Unit:
    """What a kind compared whole needs of its own (a `Kind`'s `unit`). A subclass
    is one pass over a page: it swaps its units for placeholders before the diff
    (`extract`), makes a unit that only differs by ids equal (`tie`), says which
    placeholders in a run are its own (`owns`) and how one added or removed is
    drawn (`whole`), and puts the real thing back after the diff (`restore`).
    `compare` and `draw` say, in the header's words, what counts as a change and
    how the old and the new are drawn."""

    inline = False  # a unit among the words of a block (an image), not a block's own
    placeholder_tag = None  # the tag it leaves in a run, if it leaves a tag
    order = 0  # where its pass runs among the passes (the lower first)

    def __init__(self, compare, draw, figure=False):
        # `figure`: the kind has no words of its own and is drawn as a figure (old
        # and new side by side): an image, a drawing, a diagram's text.
        self.compare, self.draw, self.figure = compare, draw, figure

    @classmethod
    def is_figure(cls, kind, text):
        """Whether the token `(kind, text)` is a unit of a figure entry."""
        return False

    @classmethod
    def extract(cls, content, side, images):
        return content, {}

    @classmethod
    def tie(cls, old, new, old_store, new_store):
        return old

    @classmethod
    def owns(cls, kind, text):
        return False

    @classmethod
    def whole(cls, text, wrapper, images):
        return f'<{wrapper} class="wc-unit">{text}</{wrapper}>'

    @classmethod
    def changed(cls, old_tok, new_tok, images):
        """(old, new) drawn for a pair of equal-looking tokens that differ, else None."""
        return None

    @classmethod
    def restore(cls, content, store, images):
        return content


class ElementUnit(Unit):
    """An element swapped for one placeholder word, whole: an equation by its TeX,
    a drawing by its safe markup, a diagram's text by its text. `typeset` says
    the page typesets it (MathJax); `figure` that it has no words of its own, as
    an image has none."""

    order = 1

    def __init__(self, compare, draw, typeset=False, figure=False):
        super().__init__(compare, draw, figure)
        self.typeset = typeset

    @classmethod
    def extract(cls, content, side, images):
        return extract_units(content)

    @classmethod
    def tie(cls, old, new, old_store, new_store):
        return _same_but_ids(old, new, old_store, new_store, UNIT_RE)

    @classmethod
    def owns(cls, kind, text):
        return kind == "word" and bool(UNIT_FULL_RE.match(text))

    @classmethod
    def is_figure(cls, kind, text):
        return cls.owns(kind, text) and text.startswith("wcfig-")

    @classmethod
    def restore(cls, content, store, images):
        return restore_units(content, store)


class PopoverUnit(Unit):
    """An evidence popover, kept whole beside its claim as a placeholder tag."""

    placeholder_tag = "wc-evpop"
    order = 0  # first: a popover goes whole, with whatever markup it holds

    @classmethod
    def extract(cls, content, side, images):
        return extract_ev_popovers(content)

    @classmethod
    def tie(cls, old, new, old_store, new_store):
        return _same_but_ids(old, new, old_store, new_store, EV_POP_RE)

    @classmethod
    def owns(cls, kind, text):
        return kind == "tag" and bool(EV_POP_RE.match(text))

    @classmethod
    def whole(cls, text, wrapper, images):
        # Stamp the op so the restore pass can chip the claim. A removed popover
        # is kept as a placeholder (it becomes a chip) rather than being dropped
        # with the rest of the deleted run.
        key = EV_POP_RE.match(text).group(1)
        return EV_POP_OP_PLACEHOLDER % (key, "add" if wrapper == "ins" else "del")

    @classmethod
    def restore(cls, content, store, images):
        return restore_ev_popovers(content, store)


class ImageUnit(Unit):
    """An `<img>`, a tag among the words of its block; its bytes are compared on
    both sites, through `images`."""

    inline = True
    order = 2  # last: an image inside any other unit is that unit's

    @classmethod
    def extract(cls, content, side, images):
        return stamp_images(content, side, images), {}

    @classmethod
    def owns(cls, kind, text):
        return kind == "tag" and tag_name(text) in registry().tags[cls]

    @classmethod
    def is_figure(cls, kind, text):
        return kind == "tag" and tag_name(text) in registry().figure_tags[cls]

    @classmethod
    def whole(cls, text, wrapper, images):
        if wrapper == "del":
            text = _old_image(text, images)
        return f'<{wrapper} class="wc-unit">{text}</{wrapper}>'

    @classmethod
    def changed(cls, old_tok, new_tok, images):
        return _image_change(old_tok, new_tok, images)

    @classmethod
    def restore(cls, content, store, images):
        return _DIGEST_RE.sub("", content)


class Kind(NamedTuple):
    """One kind of content: one entry of KINDS.

    name   what the header calls it
    tags   how it is recognised on a rendered page: its tags, and `cls`, a class
           the element must have (None: any)
    role   what the aligner does with it: `text` (a block of prose, or a line of
           source: edited when its own words change), `row` (edited when any of
           its cells' words change), `container` (aligned child by child, never
           marked itself), `inline` (words and tags inside a block), `unit`
           (compared whole by its `unit`)
    keep   what the sanitizer keeps of it, as {tag: attributes}; a unit's
           `inside` is what it keeps only inside its own element (a drawing's
           shapes)
    unit   for a unit: how a change is found and drawn (a `Unit`)
    structural  an inline kind that is never wrapped in <ins>/<del> (an evidence
           claim, whose popover must stay its direct child)
    format  an inline kind that is formatting: put on words that were already
           there, its new tag is marked"""

    name: str
    tags: tuple
    cls: str | None
    role: str
    keep: dict
    unit: Unit | None = None
    inside: dict = {}
    structural: bool = False
    format: bool = False


def _keep(*tags):
    return {t: () for t in tags}


# The one table of kinds. Add an entry here, a test in tests/test_what_changed.py
# and a case in the example workspace's sample edit (header: "Adding a kind").
_SVG_ATTRS = (
    "viewbox preserveaspectratio width height x y x1 y1 x2 y2 cx cy r rx ry dx dy "
    "d points transform fill fill-opacity fill-rule stroke stroke-width "
    "stroke-opacity stroke-linecap stroke-linejoin stroke-miterlimit "
    "stroke-dasharray stroke-dashoffset opacity text-anchor dominant-baseline "
    "font-family font-size font-weight font-style letter-spacing visibility "
    "display style"
).split()
# (an `a` keeps its words and loses its `href`: a link would leave the drawing)
_SVG_PARTS = "a g path rect circle ellipse line polyline polygon text tspan title desc"
KINDS = (
    Kind("paragraph", ("p",), None, "text", _keep("p")),
    Kind(
        "heading",
        ("h1", "h2", "h3", "h4", "h5", "h6"),
        None,
        "text",
        _keep("h1", "h2", "h3", "h4", "h5", "h6"),
    ),
    Kind("list item", ("li", "dd", "dt"), None, "text", _keep("li", "dd", "dt")),
    Kind("source line", ("wc-ln",), None, "text", {}),  # a line of `source_diff`
    Kind(
        "list",
        ("ul", "ol", "dl"),
        None,
        "container",
        {"ul": (), "ol": ("reversed", "start", "type"), "dl": ()},
    ),
    Kind("table row", ("tr",), None, "row", _keep("tr")),
    Kind(
        "table",
        ("table", "thead", "tbody", "tfoot", "caption", "colgroup", "col", "td", "th"),
        None,
        "container",
        {
            "table": (),
            "thead": (),
            "tbody": (),
            "tfoot": (),
            "caption": (),
            "colgroup": ("span",),
            "col": ("span",),
            "td": ("colspan", "headers", "rowspan"),
            "th": ("abbr", "colspan", "headers", "rowspan", "scope"),
        },
    ),
    Kind(
        "block",
        (
            "div",
            "section",
            "article",
            "aside",
            "blockquote",
            "details",
            "summary",
            "figure",
            "figcaption",
            "header",
            "footer",
            "main",
            "nav",
            "address",
            "hr",
        ),
        None,
        "container",
        {
            "div": (),
            "section": (),
            "article": (),
            "aside": (),
            "blockquote": ("cite",),
            "details": ("open",),
            "summary": (),
            "figure": (),
            "figcaption": (),
            "header": (),
            "footer": (),
            "main": (),
            "nav": (),
            "address": (),
            "hr": (),
        },
    ),
    Kind("code block", ("pre",), None, "container", _keep("pre")),
    Kind("authored edit mark", ("del", "ins"), None, "container", _keep("del", "ins")),
    Kind("link", ("a",), None, "inline", {"a": ("href",)}),
    Kind(
        "inline text",
        (
            "abbr",
            "bdi",
            "bdo",
            "br",
            "cite",
            "data",
            "dfn",
            "kbd",
            "q",
            "samp",
            "span",
            "time",
            "var",
            "wbr",
        ),
        None,
        "inline",
        {
            "abbr": (),
            "bdi": (),
            "bdo": (),
            "br": (),
            "cite": (),
            "data": (),
            "dfn": (),
            "kbd": (),
            "q": ("cite",),
            "samp": (),
            "span": ("tabindex",),
            "time": ("datetime",),
            "var": (),
            "wbr": (),
        },
    ),
    Kind(
        "formatting",
        ("b", "code", "em", "i", "mark", "s", "small", "strong", "sub", "sup", "u"),
        None,
        "inline",
        _keep(
            "b", "code", "em", "i", "mark", "s", "small", "strong", "sub", "sup", "u"
        ),
        format=True,
    ),
    Kind(
        "evidence claim",
        ("span",),
        "ev",
        "inline",
        {},
        structural=True,
    ),
    Kind(
        "equation",
        ("span",),
        "math",
        "unit",
        {},
        ElementUnit(
            compare="the TeX between \\( \\) or \\[ \\], as one unit; ids on it are not compared",
            draw="typeset as on the page, never marked inside: a display equation "
            "old above new, an inline one old then new in its line",
            typeset=True,
        ),
    ),
    Kind(
        "evidence popover",
        ("span",),
        "ev-pop",
        "unit",
        {},
        PopoverUnit(
            compare="its markup, ids aside, as part of its claim",
            draw="kept whole beside its claim, never diffed inside; one added or "
            "removed is chipped on the claim",
        ),
    ),
    Kind(
        "figure",
        ("img",),
        None,
        "unit",
        {"img": ("alt", "height", "loading", "src", "width")},
        ImageUnit(
            compare="the bytes of the file each img names, on both sites",
            draw="old and new side by side, never marked inside; the old one "
            "from the old site's bytes",
            figure=True,
        ),
    ),
    Kind(
        "inline svg",
        ("svg",),
        None,
        "unit",
        {"svg": tuple(_SVG_ATTRS)},
        ElementUnit(
            compare="its safe markup, ids aside",
            draw="old and new side by side, never marked inside",
            figure=True,
        ),
        {t: tuple(_SVG_ATTRS) for t in _SVG_PARTS.split()},
    ),
    Kind(
        "diagram text",
        ("pre",),
        "mermaid",
        "unit",
        {},
        ElementUnit(
            compare="its text (the site draws it with script at view time)",
            draw="old and new side by side, drawn by the site's own Mermaid in strict mode, else as text",
            figure=True,
        ),
    ),
)


def classes_of(open_tag):
    """The class list of an open tag."""
    m = _CLASS_RE.search(open_tag)
    return m.group(3).split() if m else []


def _names(kind, tag, classes):
    """Whether an element with this tag and these classes is one `kind` names."""
    return tag in kind.tags and (kind.cls is None or kind.cls in classes)


def role_of(tag, classes=()):
    """The role of an element in the aligner: the kind its tag and classes name
    (a kind with a class wins over one without), else a container."""
    tag = tag.lower()
    best = None
    for kind in KINDS:
        if _names(kind, tag, classes):
            if best is None or (kind.cls and not best.cls):
                best = kind
    return best.role if best else "container"


def element_unit(tag, open_tag):
    """The `ElementUnit` of the element whose open tag is `open_tag`, or None."""
    classes = classes_of(open_tag)
    for kind in KINDS:
        if isinstance(kind.unit, ElementUnit) and _names(kind, tag, classes):
            return kind.unit
    return None


def _node_name(tag):
    return "h" if HEADING_RE.match(tag) else tag  # h1-h6 are one tag: no level change


class _Registry:
    """What the entries of one KINDS say, read once: the passes over a page, and
    the tags that each pass's entries name (and of those, the figure-like ones)."""

    def __init__(self, kinds):
        self.kinds = kinds
        first = {}  # each unit class, by where its first entry stands
        for kind in kinds:
            if kind.unit is not None:
                first.setdefault(type(kind.unit), len(first))
        self.passes = tuple(sorted(first, key=lambda u: (u.order, first[u])))
        self.tags = {u: set() for u in self.passes}
        self.figure_tags = {u: set() for u in self.passes}
        for kind in kinds:
            if kind.unit is not None:
                self.tags[type(kind.unit)].update(kind.tags)
                if kind.unit.figure:
                    self.figure_tags[type(kind.unit)].update(kind.tags)


_REGISTRY = None


def registry():
    """The `_Registry` of the current KINDS (read again when KINDS is replaced)."""
    global _REGISTRY
    if _REGISTRY is None or _REGISTRY.kinds is not KINDS:
        _REGISTRY = _Registry(KINDS)
    return _REGISTRY


def passes():
    """The passes over a page, in the order they swap units out (the last restores
    first): the unit classes of the entries of KINDS, by `Unit.order`. No list of
    them is kept beside the table."""
    return registry().passes


PLACEHOLDER_TAGS = {u.placeholder_tag for u in passes() if u.placeholder_tag}
FORMAT_TAGS = {t for k in KINDS if k.format for t in k.tags}
# The tags that name a file (a `src` kept), whose bytes are compared.
FILE_TAGS = sorted(
    {
        tag
        for k in KINDS
        for tag, attrs in {**k.keep, **k.inside}.items()
        if "src" in attrs
    }
)
_IMG_RE = re.compile(
    rf"(?is)<(?:{'|'.join(FILE_TAGS)})\b[^>]*>"
)  # a tag that names a file


def names_files(markup):
    """Whether `markup` has a tag that names a file the table compares (an image, a
    video and its sources)."""
    return bool(_IMG_RE.search(markup))


# The tags of the figure entries: what the stylesheet draws as a figure.
FIGURE_TAGS = tuple(
    t for k in KINDS if k.unit is not None and k.unit.figure for t in k.tags
)
INLINE_TAGS = {
    t
    for k in KINDS
    for t in k.tags
    if k.role == "inline" or (k.unit is not None and k.unit.inline)
}
TINT_BLOCKS = {_node_name(t) for k in KINDS if k.role == "text" for t in k.tags}
ROW_TAGS = {t for k in KINDS if k.role == "row" for t in k.tags}
_UNIT_TAGS = "|".join(
    sorted({t for k in KINDS if isinstance(k.unit, ElementUnit) for t in k.tags})
)
_TYPESET_CLASSES = "|".join(
    k.cls for k in KINDS if isinstance(k.unit, ElementUnit) and k.unit.typeset
)
ELEMENT_UNIT_OPEN_RE = re.compile(rf"(?is)<({_UNIT_TAGS})(?=[\s/>])[^>]*>")
MATH_RE = re.compile(
    rf"""(?is)<span(?=\s)[^>]*?\sclass\s*=\s*["'][^"']*\b(?:{_TYPESET_CLASSES})\b"""
)


def unit_of(kind, text):
    """The pass whose placeholder or tag the token `(kind, text)` is, or None."""
    for unit in passes():
        if unit.owns(kind, text):
            return unit
    return None


def is_figure(kind, text):
    """Whether the token is a unit of a figure entry (see `Kind`)."""
    unit = unit_of(kind, text)
    return bool(unit and unit.is_figure(kind, text))


def holds_drawing(markup):
    """Whether `markup` holds a drawing: an element of an entry compared whole
    and drawn as a figure (an inline svg, a diagram's text). A page that holds
    one and nothing computed is compared, not linked."""
    for m in ELEMENT_UNIT_OPEN_RE.finditer(markup):
        unit = element_unit(m.group(1).lower(), m.group(0))
        if unit is not None and unit.figure:
            return True
    return False


# <li>x</li> and <li><p>x</p></li> are the same item: its leading paragraph is
# parsed as the item's own words, kept in their `<p>` (`_Node.wrap`).
ITEM_TAGS = {"li", "dd", "td", "th"}
WRAPPERS = {"div", "section"}  # wrapped around one block: not a change by itself
CELL_TAGS = {"td", "th"}
# Children of these are matched by position when a stretch has equal counts
# (rows by row, cells by column), so a table edit stays an edit.
TABLE_PARTS = {"table", "thead", "tbody", "tfoot", "tr"}
PAIR_RATIO = 0.3  # shared-word ratio at which two blocks count as one edited block
PAIR_BUDGET = 60_000  # most old x new block pairs compared inside one stretch

# The sanitizer, driven by KINDS: what a page keeps of any markup is what its
# kinds keep, and nothing else. `diff_content` runs it on both sides, so a page
# outside the workspace cannot skip it.
GLOBAL_SAFE_ATTRS = {"class", "dir", "lang", "role", "title"}
TAG_SAFE_ATTRS = {}
for _kind in KINDS:
    for _tag, _attrs in _kind.keep.items():
        TAG_SAFE_ATTRS.setdefault(_tag, set()).update(_attrs)
SAFE_TAGS = set(TAG_SAFE_ATTRS)
INSIDE_TAGS = {
    k.tags[0]: {t: set(a) for t, a in k.inside.items()} for k in KINDS if k.inside
}
# These go with everything inside them (a script, a style, a plugin, a form).
DROP_CONTENT_TAGS = {
    "applet",
    "audio",
    "base",
    "button",
    "canvas",
    "embed",
    "form",
    "iframe",
    "input",
    "link",
    "math",
    "meta",
    "object",
    "option",
    "script",
    "select",
    "style",
    "template",
    "textarea",
    "video",
}
URL_ATTRS = {"cite", "href", "poster", "src"}
_ID_VALUE_RE = re.compile(r"[A-Za-z_][\w:.-]{0,127}$")
_CSS_VALUE_RE = re.compile(r"(?i)url\s*\(|expression|javascript|@import|[\\<>{}]")
# A drawing's style: paint and text properties only, never a url() or an import.
_SVG_STYLE_PROPS = {a for a in _SVG_ATTRS if a not in ("style", "d", "points")} - {
    "viewbox",
    "preserveaspectratio",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "dx",
    "dy",
    "transform",
}


def rebase_relative_url(value, source):
    """Resolve a page-relative URL from `source`, the page's site path, to one
    relative to the site root, where the diff page lives."""
    parts = urlsplit(value)
    if not source or parts.scheme or parts.netloc:
        return value
    if not parts.path and not parts.query:
        return value
    if parts.path.startswith("/"):
        return value
    path = posixpath.normpath(
        posixpath.join(posixpath.dirname(source), parts.path) if parts.path else source
    )
    if path == ".." or path.startswith("../"):
        return value
    if parts.path.endswith("/") and not path.endswith("/"):
        path += "/"
    # A colon in the first segment would read as a scheme ("../javascript:x").
    if ":" in path.split("/", 1)[0]:
        path = "./" + path
    return parts._replace(path=path).geturl()


def safe_url(value):
    """Allow ordinary links/resources, never executable URL schemes."""
    compact = re.sub(r"[\x00-\x20\x7f]+", "", html.unescape(value))
    scheme = urlsplit(compact).scheme.lower()
    return not scheme or scheme in {"http", "https", "mailto"}


def _svg_style(value):
    """The declarations of an inline style a drawing may keep."""
    kept = []
    for decl in html.unescape(value).split(";"):
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if prop in _SVG_STYLE_PROPS and val and not _CSS_VALUE_RE.search(val):
            kept.append(f"{prop}: {val}")
    return "; ".join(kept)


class _SafeFragmentParser(HTMLParser):
    """Strict-allowlist sanitizer for rendered page fragments: the tags and
    attributes of KINDS, URLs that are relative, http, https or mailto, and
    nothing that runs (no script, no event handler, no inline style but a
    drawing's paint, no external reference from a drawing)."""

    def __init__(self, base="", ids=False):
        super().__init__(convert_charrefs=False)
        self.out = []
        self.drop_stack = []
        self.inside = []  # the unit elements open (a drawing), innermost last
        self.base = base
        self.ids = ids

    def _allowed(self, tag):
        """The attributes kept for `tag` here, or None when it is dropped."""
        if self.inside:
            kept = INSIDE_TAGS[self.inside[-1]].get(tag)
            if kept is None and tag == self.inside[-1]:
                kept = TAG_SAFE_ATTRS[tag]
            return kept
        return TAG_SAFE_ATTRS.get(tag)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        # A void element has no content and no end tag, so it opens no scope: what
        # follows it is the page's again.
        scope = tag not in VOID_TAGS
        if self.drop_stack:
            if tag in DROP_CONTENT_TAGS and scope:
                self.drop_stack.append(tag)
            return
        if tag in DROP_CONTENT_TAGS:
            if scope:
                self.drop_stack.append(tag)
            return
        allowed = self._allowed(tag)
        if allowed is None:
            if (
                self.inside and scope
            ):  # an unknown element in a drawing goes with its content
                self.drop_stack.append(tag)
            return
        allowed = GLOBAL_SAFE_ATTRS | set(allowed)
        clean = []
        for name, value in attrs:
            name = name.lower()
            if name == "id" and self.ids and value and _ID_VALUE_RE.match(value):
                clean.append(f'id="{html.escape(value, quote=True)}"')
                continue
            if name not in allowed and not name.startswith("aria-"):
                continue
            if name == "tabindex" and value not in ("0", "-1"):
                continue  # focusable evidence claims only; no tab-order jumps
            if value is None:
                clean.append(name)
                continue
            if name in URL_ATTRS:
                if not safe_url(value):
                    continue
                value = rebase_relative_url(value, self.base)
                if not safe_url(value):
                    continue
            elif self.inside or tag in INSIDE_TAGS:  # (a drawing's own too)
                if name == "style":
                    value = _svg_style(value)
                    if not value:
                        continue
                elif _CSS_VALUE_RE.search(html.unescape(value)):
                    continue  # no reference out of a drawing (nor an escape for one)
            clean.append(f'{name}="{html.escape(value, quote=True)}"')
        if tag in INSIDE_TAGS:
            self.inside.append(tag)
        suffix = (" " + " ".join(clean)) if clean else ""
        self.out.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            return
        mark = len(self.out)
        self.handle_starttag(tag, attrs)
        if self.drop_stack and self.drop_stack[-1] == tag:
            self.drop_stack.pop()  # `<foreignObject/>` has no content to drop
        elif len(self.out) > mark:
            if tag in INSIDE_TAGS and self.inside and self.inside[-1] == tag:
                self.inside.pop()
            if tag not in VOID_TAGS:
                self.out.append(f"</{tag}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.drop_stack:
            if tag == self.drop_stack[-1]:
                self.drop_stack.pop()
            return
        if self._allowed(tag) is not None and tag not in VOID_TAGS:
            if self.inside and self.inside[-1] == tag:
                self.inside.pop()
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.drop_stack:
            self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.drop_stack:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.drop_stack:
            self.out.append(f"&#{name};")


def sanitize_fragment(content, rel="", ids=False):
    """Return inert static HTML suitable for embedding in a page: only what the
    kinds of KINDS keep, comments and ids dropped (`ids=True` keeps an id that
    is a plain name).

    `rel` is the source page's site path; its relative links are rebased to
    the site root so they resolve from the diff page."""
    parser = _SafeFragmentParser(rel, ids)
    parser.feed(content)
    parser.close()
    return "".join(parser.out)


# MathJax, as Quarto loads it on its own pages, only for a page that has an
# equation; the source view (`.wc-src`) is left out of typesetting. TeX is text to
# the sanitizer, and MathJax can draw it as a link (`\href{javascript:...}{x}`),
# so the page typesets only with MathJax's own safe component, pinned like the main
# script, with executable schemes off and classes, ids and styles constrained: the
# page is published on the repo's Pages origin, where nothing in an edit may run.
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml-full.js"
MATHJAX_SRI = "sha384-NR8saakDju74wZ6sprPPhEoWbaP3iVtXVJH12mRSiaIgxMdi33mOQj8bnF2WxzY3"
MATHJAX_SAFE_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/ui/safe.js"
MATHJAX_SAFE_SRI = (
    "sha384-BAIqbtawDyB5QXh8BrGd4h2FmhlZB70FJqMpHt2LxKkPSRa29VXhrB/DV3xLP+/B"
)
MATHJAX_CONFIG = {
    "tex": {"inlineMath": [["\\(", "\\)"]], "displayMath": [["\\[", "\\]"]]},
    "options": {
        "ignoreHtmlClass": "wc-src",
        "safeOptions": {
            "allow": {
                "URLs": "safe",
                "classes": "safe",
                "cssIDs": "safe",
                "styles": "safe",
            },
            "safeProtocols": {
                "http": True,
                "https": True,
                "file": False,
                "javascript": False,
                "data": False,
            },
        },
    },
    # Typeset by the last script, and only when the safe component has loaded.
    "startup": {"typeset": False},
}
# The main bundle builds MathJax's handler and document as soon as it has loaded,
# before the next <script> runs, so a safe.js loaded after it would reach no
# document. So the config's `ready` is held (an empty function): the document is
# built by `defaultReady()` in the last script, after safe.js has run, and only
# if it did; without it nothing is built and nothing is typeset.
MATHJAX_SCRIPT = (
    f"<script>window.MathJax = {json.dumps(MATHJAX_CONFIG)};"
    "window.MathJax.startup.ready = function () {};</script>"
    f'<script src="{MATHJAX_URL}" integrity="{MATHJAX_SRI}" '
    'crossorigin="anonymous"></script>'
    f'<script src="{MATHJAX_SAFE_URL}" integrity="{MATHJAX_SAFE_SRI}" '
    'crossorigin="anonymous"></script>'
    "<script>(function () { var m = window.MathJax;"
    " if (m && m.startup && m.startup.defaultReady && m._ && m._.ui && m._.ui.safe) {"
    " m.startup.defaultReady();"
    " m.startup.promise = m.startup.promise.then("
    "function () { return m.typesetPromise(); }); } })();</script>"
)


def math_script(*fragments):
    """The scripts that typeset the equations of a page made of `fragments`:
    MathJax 3.2.2 and its safe component, pinned from cdn.jsdelivr.net with their
    integrity hashes, or "" when none has an equation."""
    return MATHJAX_SCRIPT if any(MATH_RE.search(f) for f in fragments) else ""


# Mermaid, for a page that has a changed Mermaid diagram: Quarto writes a
# `{mermaid}` cell as `<pre class="mermaid mermaid-js">` holding the diagram's text
# and the site draws it at view time with the `mermaid.min.js` it ships in
# `site_libs`. What changed draws the old and new text of each `.wc-unit` pair with
# the same release (11.12.0, as Quarto 1.9 ships it), pinned from cdn.jsdelivr.net
# with its integrity hash like MathJax; it never loads a file a compared site
# ships, which a pull request could fill with any code. The text comes from an
# edit, so Mermaid runs in its strict
# mode (labels are encoded and sanitized; no click, no link, no script) with its
# `secure` keys (a `%%{init}%%` directive cannot lower the level, turn on loading
# or add CSS), nothing is drawn on load, and the SVG it returns is scrubbed once
# more before it joins the page. A diagram it cannot draw stays as its text.
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.min.js"
MERMAID_SRI = "sha384-o+g/BxPwhi0C3RK7oQBxQuNimeafQ3GE/ST4iT2BxVI4Wzt60SH4pq9iXVYujjaS"
MERMAID_UNIT_RE = re.compile(
    r'(?is)<(?:del|ins)\s+class="wc-unit"\s*>\s*<pre\s+class="mermaid\b'
)
MERMAID_CONFIG = {
    "startOnLoad": False,
    "securityLevel": "strict",
    "suppressErrorRendering": True,
    "logLevel": "fatal",
    "secure": [
        "secure",
        "securityLevel",
        "startOnLoad",
        "maxTextSize",
        "suppressErrorRendering",
        "maxEdges",
        "themeCSS",
        "logLevel",
    ],
}
MERMAID_JS = r"""
(function () {
  "use strict";
  var mermaid = window.mermaid;
  var pres = Array.prototype.slice.call(
    document.querySelectorAll(".wc-unit > pre.mermaid"));
  // No Mermaid (the script did not load), or nothing to draw: the text stays.
  if (!mermaid || !pres.length || !mermaid.initialize || !mermaid.render) return;
  var root = document.documentElement;
  var mode = root.getAttribute("data-wc-mode");
  var dark = mode ? mode === "dark" : !!(window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches);
  var config = %CONFIG%;
  config.theme = dark ? "dark" : "default";
  try { mermaid.initialize(config); } catch (e) { return; }
  var DROP = /^(script|iframe|object|embed|animate|set|animatetransform|animatemotion)$/i;
  // The SVG Mermaid returns was sanitized by its strict mode; this is a second,
  // independent pass over it, in a document that runs nothing: no script, no
  // event handler, and no link or reference but one inside the drawing.
  function scrub(node) {
    Array.prototype.slice.call(node.children).forEach(function (child) {
      if (DROP.test(child.localName || "")) { child.remove(); return; }
      Array.prototype.slice.call(child.attributes).forEach(function (a) {
        var n = a.name.toLowerCase();
        var ref = n === "href" || n === "xlink:href" || n === "src";
        if (n.indexOf("on") === 0 || (ref && a.value.trim().charAt(0) !== "#"))
          child.removeAttribute(a.name);
      });
      scrub(child);
    });
  }
  function draw(pre, svg) {
    var doc = new DOMParser().parseFromString(
      "<!doctype html><html><body>" + svg + "</body></html>", "text/html");
    scrub(doc.body);
    var kept = Array.prototype.slice.call(doc.body.childNodes);
    if (!doc.body.querySelector("svg")) return false;
    while (pre.firstChild) pre.removeChild(pre.firstChild);
    kept.forEach(function (n) { pre.appendChild(document.importNode(n, true)); });
    pre.setAttribute("data-wc-drawn", "");
    return true;
  }
  // One diagram at a time, each its own failure: a diagram that does not parse
  // stays as its text. Drawn once the page and its fonts have loaded, as the
  // site's own script draws, so that Mermaid measures the labels it will show.
  function start() {
    var chain = Promise.resolve();
    pres.forEach(function (pre, i) {
      chain = chain.then(function () {
        var id = "wc-mermaid-" + i;
        var text = pre.textContent.replace(/\u00a0/g, " ");
        return Promise.resolve().then(function () { return mermaid.render(id, text); })
          .then(function (out) { draw(pre, out && out.svg); })
          .catch(function () {})
          .then(function () {
            var left = document.getElementById("d" + id) || document.getElementById(id);
            if (left && !pre.contains(left)) left.remove();
          });
      });
    });
    // A drawing has a size now: a pair too wide for half the column is stacked.
    chain.then(function () { if (window.wcPairLayout) window.wcPairLayout(); });
  }
  if (document.readyState === "complete") start();
  else window.addEventListener("load", start);
})();
""".replace("%CONFIG%", json.dumps(MERMAID_CONFIG))


def has_mermaid_unit(*fragments):
    """Whether any of `fragments` holds a Mermaid diagram drawn as old and new."""
    return any(MERMAID_UNIT_RE.search(f) for f in fragments)


def mermaid_script(*fragments):
    """The scripts that draw the Mermaid diagrams of a page made of `fragments`:
    Mermaid 11.12.0 pinned from cdn.jsdelivr.net with its integrity hash, then the
    drawing script. "" when none has a changed Mermaid diagram. Without a network
    the pinned script does not load and the diagram's text stays, wrapped."""
    if not has_mermaid_unit(*fragments):
        return ""
    return (
        f'<script src="{MERMAID_URL}" integrity="{MERMAID_SRI}" '
        'crossorigin="anonymous"></script>'
        f"<script>{MERMAID_JS}</script>"
    )


# A changed figure or drawing is set old beside new (the stylesheet) while each is
# no wider, at its natural size, than half the column; a wider one would be scaled
# down until its labels cannot be read, so its pair is set old above new, at that
# natural size up to the full column. The natural size is the one the page knows:
# an image's width attribute, else the file's own width; an inline svg's, or a drawn
# Mermaid diagram's, max-width, else its width, else its viewBox. Half the column is
# measured in the side-by-side layout itself (the box of a unit less its padding), so
# the rule is the same at 390px. Run on load (an image has its size then), on resize,
# when an image loads late, and by the Mermaid script once it has drawn.
PAIR_UNIT_RE = re.compile(
    r'(?is)<(?:del|ins)\s+class="wc-unit"\s*>\s*<(?:img\b|svg\b|pre\s+class="mermaid\b)'
)
PAIR_JS = r"""
(function () {
  "use strict";
  var STACK = "wc-pair-stack";
  function num(v) {
    var n = parseFloat(v);
    return isFinite(n) && n > 0 ? n : 0;
  }
  // A width written as a plain number of pixels (not a percentage or a unit).
  function attrPx(el, name) {
    var v = el.getAttribute(name);
    return v && /^\s*[0-9.]+\s*(px)?\s*$/i.test(v) ? num(v) : 0;
  }
  // The width a figure is drawn at when nothing scales it, or 0 when not known.
  function natural(unit) {
    var el = unit.querySelector("img, svg");
    if (!el) return 0;
    if (el.localName === "img") return attrPx(el, "width") || num(el.naturalWidth);
    var cap = /max-width:\s*([0-9.]+)px/i.exec(el.getAttribute("style") || "");
    if (cap) return num(cap[1]);
    var w = attrPx(el, "width");
    if (w) return w;
    var box = (el.getAttribute("viewBox") || "").trim().split(/[\s,]+/);
    return box.length === 4 ? num(box[2]) : 0;
  }
  // The room one unit has side by side: its box less its padding.
  function room(unit) {
    var style = window.getComputedStyle ? window.getComputedStyle(unit) : null;
    var pad = style ? num(style.paddingLeft) + num(style.paddingRight) : 0;
    return unit.clientWidth - pad;
  }
  function units(parent) {
    var out = [], ok = true;
    Array.prototype.forEach.call(parent.children, function (c) {
      var u = /^(del|ins)$/.test(c.localName) && c.classList.contains("wc-unit");
      if (u) out.push(c); else ok = false;
    });
    var kinds = out.map(function (u) { return u.localName; });
    return ok && kinds.indexOf("del") >= 0 && kinds.indexOf("ins") >= 0 ? out : null;
  }
  function pairs() {
    var seen = [], found = [];
    Array.prototype.forEach.call(
      document.querySelectorAll("del.wc-unit, ins.wc-unit"), function (u) {
        var parent = u.parentElement;
        if (!parent || seen.indexOf(parent) >= 0) return;
        seen.push(parent);
        var list = /^(p|div|figure)$/.test(parent.localName) && units(parent);
        if (list) found.push({ parent: parent, units: list });
      });
    return found;
  }
  function figures(pair) {
    return pair.units.map(function (u) { return u.querySelector("img, svg"); })
      .filter(Boolean);
  }
  function layout() {
    var all = pairs();
    // Side by side first, so that every measure is of that layout.
    all.forEach(function (pair) {
      pair.parent.classList.remove(STACK);
      figures(pair).forEach(function (f) { f.style.width = ""; });
    });
    all.forEach(function (pair) {
      pair.wide = pair.units.some(function (u) {
        var w = natural(u), r = room(u);
        return w > 0 && r > 0 && w > r;
      });
      pair.widths = pair.units.map(natural);
    });
    all.forEach(function (pair) {
      if (!pair.wide) return;
      pair.parent.classList.add(STACK);
      pair.units.forEach(function (u, i) {
        var f = u.querySelector("img, svg");
        if (f && pair.widths[i]) f.style.width = "min(" + pair.widths[i] + "px, 100%)";
      });
    });
  }
  window.wcPairLayout = layout;
  // An image with no size yet lays the pair out again when it has one.
  Array.prototype.forEach.call(document.querySelectorAll(".wc-unit img"), function (img) {
    if (!img.complete) img.addEventListener("load", layout);
  });
  var queued = false;
  window.addEventListener("resize", function () {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || window.setTimeout)(function () {
      queued = false;
      layout();
    });
  });
  if (document.readyState === "complete") layout();
  else window.addEventListener("load", layout);
})();
"""


def pair_script(*fragments):
    """The script that sets a wide changed figure's old above new, for a page made
    of `fragments`: "" when none has a changed figure or drawing."""
    if not any(PAIR_UNIT_RE.search(f) for f in fragments):
        return ""
    return f"<script>{PAIR_JS}</script>"


_START_RE = re.compile(r"(?is)^<[a-zA-Z0-9-]+")
_LINK_ATTR_RE = re.compile(r"""(?is)(\s(?:href|src)\s*=\s*)(["'])(.*?)\2""")
_TITLE_RE = re.compile(r"(?is)\stitle\s*=")


def _add_class(tag, name):
    m = _CLASS_RE.search(tag)
    if m:
        return (
            tag[: m.start()]
            + f"{m.group(1)}{m.group(2)}{m.group(3)} {name}{m.group(2)}"
            + tag[m.end() :]
        )
    return _START_RE.sub(lambda s: f'{s.group(0)} class="{name}"', tag, count=1)


def _align_key(tok):
    """What the word diff aligns on: a tag without its link target.

    A link or image whose href/src alone changed still lines up with its old
    self; the target change is then marked on the kept tag (`_mark_target`).
    """
    kind, text = tok
    if kind == "tag" and text.startswith("<") and not text.startswith("</"):
        if unit_of(kind, text):
            # A figure is its file: one with another src is another figure.
            return drop_id_attrs(_DIGEST_RE.sub("", text))
        return drop_id_attrs(_DIGEST_RE.sub("", _LINK_ATTR_RE.sub(r"\1\2\2", text)))
    return text


def _mark_target(old_tag, new_tag):
    """The new tag with the link target it replaced: marked, old kept for display."""
    old = {m.group(1).strip().split("=")[0].lower(): m.group(3)
           for m in _LINK_ATTR_RE.finditer(old_tag)}  # fmt: skip
    was = " ".join(
        html.unescape(v)
        for k, v in old.items()
        if not re.search(rf"(?is)\s{k}\s*=\s*([\"']){re.escape(v)}\1", new_tag)
    )
    tag = _add_class(new_tag, "wc-link-changed")
    extra = f' data-wc-was="{html.escape(was, quote=True)}"'
    if not _TITLE_RE.search(tag):
        extra += f' title="{html.escape("was: " + was, quote=True)}"'
    return re.sub(r"\s*/?>$", lambda m: extra + m.group(0), tag, count=1)


def _mark_old_target(old_tag):
    """The old tag of a link or image whose target changed, marked for the old
    side (the new side's tag carries the old target beside the new)."""
    return _add_class(old_tag, "wc-link-was")


class _Node:
    """One piece of a page: an element, or a run of words and inline tags."""

    def __init__(self, kind, name="", open_="", ws="", tokens=None, drop_ids=False):
        self.kind = kind  # "el" or "run"
        self.name = name  # a heading is "h"
        self.sig = drop_id_attrs(open_)  # what equal means: ids are render noise
        self.open = (
            self.sig if drop_ids else open_
        )  # the old page's ids may be the new's
        self.close = ""
        self.tail = ""  # whitespace before the close tag
        self.ws = ws  # whitespace before this node, from its own page
        self.tokens = tokens or []
        self.children = []
        self.void = False
        self.wrap = ("", "")  # a run's own paragraph tags (an item's leading <p>)
        self._key = self._words = None

    def key(self):
        """Equal keys mean equal markup, whitespace between blocks aside."""
        if self._key is None:
            if self.kind == "run":
                body = "".join(
                    " " if k == "space" else drop_id_attrs(t) if k == "tag" else t
                    for k, t in self.tokens
                ).strip()
            else:
                body = self.sig + "\0".join(c.key() for c in self.children) + self.close
            self._key = hashlib.sha1(body.encode("utf-8")).hexdigest()
        return self._key

    def words(self):
        """Bag of visible words, plus how many images and evidence quotes."""
        if self._words is None:
            if self.kind == "run":
                bag = Counter(
                    t for k, t in self.tokens if k == "word" and not is_figure(k, t)
                )
                # (a figure, a popover, a drawing: a unit with no words)
                extra = sum(1 for k, t in self.tokens if unit_of(k, t))
            else:
                bag, extra = Counter(), 0
                for c in self.children:
                    cb, ce = c.words()
                    bag.update(cb)
                    extra += ce
            self._words = (bag, extra)
        return self._words

    def visible(self):
        bag, extra = self.words()
        return bool(bag) or bool(extra)

    def _run(self, inner):
        return self.ws + self.wrap[0] + inner + self.wrap[1]

    def around(self, inner):
        """The node's own tags around `inner` (its children, as drawn)."""
        return self.ws + self.open + inner + self.tail + self.close

    def raw(self):
        if self.kind == "run":
            return self._run("".join(t for _, t in self.tokens))
        if self.void:
            return self.ws + self.open
        return self.around("".join(c.raw() for c in self.children))


def _is_block_tag(tok):
    kind, text = tok
    return (
        kind == "tag"
        and not text.startswith("<!")
        and not is_inline_tag(text)
        and not unit_of(kind, text)
        and bool(tag_name(text))
    )


def is_void(tok):
    return tag_name(tok) in VOID_TAGS or tok.rstrip().endswith("/>")


def _inline_nested(tokens):
    stack = []
    for kind, text in tokens:
        if kind != "tag" or not is_inline_tag(text):
            continue
        name = tag_name(text)
        if text.startswith("</"):
            if not stack or stack.pop() != name:
                return False
        elif not (text.rstrip().endswith("/>") or name in VOID_TAGS):
            stack.append(name)
    return not stack


def _hoist_paragraph(item):
    """Make an item's leading `<p>x</p>` its own words, as in `<li>x</li>`: the
    run keeps the paragraph's tags, so both shapes of an item pair and compare."""
    first = item.children[0] if item.children else None
    if (
        item.name in ITEM_TAGS
        and first is not None
        and first.name == "p"
        and not first.void
        and len(first.children) == 1
        and first.children[0].kind == "run"
    ):
        run = first.children[0]
        run.ws, run.wrap = first.ws + run.ws, (first.open, first.tail + first.close)
        item.children[0] = run


def parse_blocks(tokens, drop_ids=False):
    """Split a token list into a tree of blocks, or None if it does not nest.

    Element nodes are every non-inline tag; the words and inline tags between
    them form `run` nodes. Whitespace between blocks is kept on the node after
    it, so it never takes part in the alignment. `drop_ids` takes the ids off
    every block (the old page's: the new page may own them).
    """
    root = _Node("el")
    stack, run, pending = [root], [], ""

    def flush():
        nonlocal run, pending
        if not run:
            return True
        if any(n.name == "pre" for n in stack):
            # Whitespace in a code block is the code's: each run of it is a
            # token that is compared and marked like a word (kind "ws").
            run = [("ws", t) if k == "space" else (k, t) for k, t in run]
        if all(k == "space" for k, _ in run):
            pending += "".join(t for _, t in run)
        elif _inline_nested(run):
            stack[-1].children.append(_Node("run", ws=pending, tokens=run))
            pending = ""
        else:
            return False
        run = []
        return True

    for tok in tokens:
        if not _is_block_tag(tok):
            run.append(tok)
            continue
        if not flush():
            return None
        text = tok[1]
        name = "h" if HEADING_RE.match(tag_name(text)) else tag_name(text)
        if text.startswith("</"):
            if len(stack) < 2 or stack[-1].name != name:
                return None
            node = stack.pop()
            node.close, node.tail, pending = text, pending, ""
            _hoist_paragraph(node)
        else:
            node = _Node("el", name=name, open_=text, ws=pending, drop_ids=drop_ids)
            pending = ""
            stack[-1].children.append(node)
            if is_void(text):
                node.void = True
            else:
                stack.append(node)
    if not flush() or len(stack) != 1:
        return None
    root.tail = pending
    return root


def _similarity(old, new):
    """Shared-word ratio of two blocks, or -1 when they cannot be one block."""
    if old.kind != new.kind or old.name != new.name:
        return -1.0
    (a, ea), (b, eb) = old.words(), new.words()
    na, nb = sum(a.values()), sum(b.values())
    if not na + nb:
        return 1.0 if ea == eb else 0.0
    shared = sum((a & b).values())
    # Half the Dice ratio, half containment of the shorter block in the longer,
    # so a paragraph that only gained or lost a clause still pairs.
    return (shared / (na + nb) + shared / max(min(na, nb), 1)) / 2


def _sole_child(node):
    """The one block a wrapper (div, section) holds, else None."""
    if node.kind == "el" and node.name in WRAPPERS and len(node.children) == 1:
        return node.children[0] if node.children[0].kind == "el" else None
    return None


def _pairing(old, new):
    """(ratio, how) for two blocks: 'pair' when they are one block, 'into' when
    `new` is a wrapper around `old`, 'outof' when `old` was one around `new`;
    ratio is -1 when they are none of these."""
    ratio = _similarity(old, new)
    if ratio >= 0:
        return ratio, "pair"
    inner = _sole_child(new)
    if inner is not None and _pairing(old, inner)[0] >= 0:
        return _pairing(old, inner)[0], "into"
    inner = _sole_child(old)
    if inner is not None and _pairing(inner, new)[0] >= 0:
        return _pairing(inner, new)[0], "outof"
    return -1.0, ""


def _pair_stretch(olds, news, parent):
    """Order a replaced stretch of blocks as ('del', o) / ('ins', n) / ('pair', o, n),
    or ('into', o, n) / ('outof', o, n) for a block wrapped or unwrapped.

    Table rows and cells with equal counts pair by position. Otherwise pairing
    is difflib.Differ's idea (`_fancy_replace`): the most similar old/new pair
    in the stretch, if similar enough, is one edited block, and the stretches
    before and after it are paired the same way.
    """
    if (
        parent in TABLE_PARTS
        and len(olds) == len(news)
        and all(_similarity(o, n) >= 0 for o, n in zip(olds, news))
    ):
        return [("pair", o, n) for o, n in zip(olds, news)]
    if len(olds) == len(news) == 1 and olds[0].kind == news[0].kind == "run":
        return [("pair", olds[0], news[0])]  # the same words, edited
    if len(olds) * len(news) > PAIR_BUDGET:
        return [("del", o) for o in olds] + [("ins", n) for n in news]

    # Each old/new pair is scored once (the PAIR_BUDGET bounds that work), then
    # taken best first, a pair only when it keeps the pairs already taken in
    # order: the same pairs as taking the best and pairing what lies either side
    # of it in turn, without scoring the pairs again for each side.
    scored = []
    for i, o in enumerate(olds):
        for j, n in enumerate(news):
            ratio, how = _pairing(o, n)
            if ratio >= PAIR_RATIO:
                scored.append((-ratio, i, j, how))
    scored.sort()
    rows, cols, hows = [], [], []  # the pairs taken, by old index
    for _, i, j, how in scored:
        k = bisect.bisect_left(rows, i)
        if k < len(rows) and (rows[k] == i or cols[k] <= j):
            continue  # that old block is taken, or the pair would cross one
        if k and cols[k - 1] >= j:
            continue
        rows.insert(k, i)
        cols.insert(k, j)
        hows.insert(k, how)
    steps, i0, j0 = [], 0, 0
    for i, j, how in zip(rows, cols, hows):
        steps += [("del", o) for o in olds[i0:i]] + [("ins", n) for n in news[j0:j]]
        steps.append((how, olds[i], news[j]))
        i0, j0 = i + 1, j + 1
    return steps + [("del", o) for o in olds[i0:]] + [("ins", n) for n in news[j0:]]


_SPAN_RE = re.compile(r"(?i)\b(?:col|row)span\s*=")


def _header_cells(table):
    """The cells of a table's header row (the first row, when it is in a <thead>
    or holds only <th>), or None: no such row, or a cell that spans columns."""
    for part in table.children:
        if part.name == "tr":
            row, in_head = part, False
        elif part.name in ("thead", "tbody", "tfoot"):
            row = next((r for r in part.children if r.name == "tr"), None)
            in_head = part.name == "thead"
        else:
            continue
        if row is None:
            continue
        cells = [c for c in row.children if c.kind == "el"]
        if (
            cells
            and all(c.name in CELL_TAGS and not _SPAN_RE.search(c.open) for c in cells)
            and (in_head or all(c.name == "th" for c in cells))
        ):
            return cells
        return None
    return None


def _table_columns(old_table, new_table):
    """The columns of a table pair as (old index, new index) in page order, an
    index None where the column was added or removed, aligned on the header
    rows; None when either table has no plain header row. Every body row's cells
    follow this one correspondence, so an edited value stays in its column."""
    old_cells, new_cells = _header_cells(old_table), _header_cells(new_table)
    if old_cells is None or new_cells is None:
        return None
    at_old = {id(c): i for i, c in enumerate(old_cells)}
    at_new = {id(c): j for j, c in enumerate(new_cells)}
    cols = []
    for op, i1, i2, j1, j2 in _align(
        [c.key() for c in old_cells], [c.key() for c in new_cells]
    ):
        if op == "equal":
            cols += zip(range(i1, i2), range(j1, j2))
            continue
        for step in _pair_stretch(old_cells[i1:i2], new_cells[j1:j2], "tr"):
            cols.append(
                (
                    at_old.get(id(step[1])) if step[0] != "ins" else None,
                    at_new.get(id(step[-1])) if step[0] != "del" else None,
                )
            )
    return cols


def _by_column(olds, news, parent, cols):
    """The steps of one table row's cells under the table's columns, or None
    when the row is not one cell per column on both sides."""
    if cols is None or parent not in ROW_TAGS:
        return None
    if len(olds) != sum(i is not None for i, _ in cols) or len(news) != sum(
        j is not None for _, j in cols
    ):
        return None
    steps = []
    for i, j in cols:
        if j is None:
            steps.append(("del", olds[i]))
        elif i is None:
            steps.append(("ins", news[j]))
        elif olds[i].key() == news[j].key():
            steps.append(("equal", olds[i], news[j]))
        elif _similarity(olds[i], news[j]) >= 0:
            steps.append(("pair", olds[i], news[j]))
        else:
            steps += [("del", olds[i]), ("ins", news[j])]
    return steps


def _steps(olds, news, parent, cols):
    """How two lists of sibling blocks line up: ('equal', o, n) for blocks
    alike, then the steps of `_pair_stretch` for each stretch that differs; a
    table row's cells follow the table's columns instead."""
    steps = _by_column(olds, news, parent, cols)
    if steps is not None:
        return steps
    steps = []
    for op, i1, i2, j1, j2 in _align([o.key() for o in olds], [n.key() for n in news]):
        if op == "equal":
            steps += [("equal", o, n) for o, n in zip(olds[i1:i2], news[j1:j2])]
        else:
            steps += _pair_stretch(olds[i1:i2], news[j1:j2], parent)
    return steps


def _moves_columns(cols):
    """Whether a table's column plan is not the identity (a column was added or
    removed): then a row's cells are not under the same headers on both sides."""
    return cols is not None and any(i != j for i, j in cols)


def _whole_row_cells(node, wrapper, cols, images):
    """The cells of a wholly added or removed row under the table's columns, an
    empty cell where the row's side has no such column; None when the row is not
    one cell per column on its side (a span, text beside the cells)."""
    mine = 1 if wrapper == "ins" else 0
    kids = node.children
    if len(kids) != sum(c[mine] is not None for c in cols) or any(
        k.kind != "el" or k.name not in CELL_TAGS for k in kids
    ):
        return None
    cells = iter(kids)
    gap = "th" if all(k.name == "th" for k in kids) else "td"
    return "".join(
        _render_whole(next(cells), wrapper, False, images)
        if c[mine] is not None
        else f"<{gap}></{gap}>"
        for c in cols
    )


def _render_whole(node, wrapper, top=True, images=None, cols=None):
    """An added or removed block: its own tags kept, its words marked.

    Only the block itself gets the light class; the words inside keep their
    <ins>/<del> (the stylesheet draws those lightly inside such a block). A
    removed block drops its ids, which the new page may still own. A table row
    (or a tbody holding rows) follows the table's columns `cols`, so that its
    values stay under their headers.
    """
    if node.kind == "run":
        return node._run(emit_run(node.tokens, wrapper, images))
    open_ = _add_class(node.open, BLOCK_CLASS[wrapper]) if top else node.open
    if node.void:
        return node.ws + open_
    inner = None
    if _moves_columns(cols) and node.name in ROW_TAGS:
        inner = _whole_row_cells(node, wrapper, cols, images)
    if inner is None:
        pass_cols = cols if node.name in TABLE_PARTS else None
        inner = "".join(
            _render_whole(c, wrapper, False, images, pass_cols) for c in node.children
        )
    return node.ws + open_ + inner + node.tail + node.close


# What `_diff_children` draws, as (runs, blocks): which side's words a run shows
# (both: the removed and the added in one run; old; new), and whether a block is
# drawn (inter: yes; none: no block, only the runs).
BOTH = ("both", "inter")  # a page, and a container inside an edited block
NEW_MIXED = ("new", "inter")  # the new copy of an edited source line
OLD_OWN = ("old", "none")  # the old copy of an edited source line: its words


def _side_raw(o, n, side):
    """An unchanged node as one side of its page has it."""
    return (o if side == "old" else n).raw()


def _edit_copies(o, n, old_in, new_in):
    """An edited source line as its old copy, then its new copy (GitHub's two
    rows), each in its own side's tag, with the light shade of its side."""
    return (
        o.ws
        + _add_class(o.open, "wc-edit-old")
        + old_in
        + o.tail
        + o.close
        + n.ws
        + _add_class(n.open, "wc-edit-new")
        + new_in
        + n.tail
        + n.close
    )


def _diff_children(olds, news, parent, images=None, mode=BOTH, rows=False, cols=None):
    """Diff two lists of sibling blocks; returns (html, changed, own, inplace).

    An edited block (a paragraph, heading, list item, table row) is drawn once,
    in its new tag, the words of both sides marked in it. With `rows` (the lines
    of a source view) an edited line is drawn as GitHub does: its old copy, then
    its new copy, each with the words of its own side marked (`mode` says what
    is drawn, see BOTH and the rest). `own` is set when a run of words directly
    in these children changed (what makes a line an edit), `inplace` when any
    paired block's words changed below.
    """
    runs, blocks = mode
    # What a container inside an edited text block draws: the page's own way.
    inner_mode = BOTH if blocks == "inter" else mode
    out = []
    changed = own = inplace = False
    for step in _steps(olds, news, parent, cols):
        if step[0] == "equal":
            o, n = step[1], step[2]
            if n.kind == "run":
                out.append(_side_raw(o, n, runs))
            elif blocks != "none":
                if _moves_columns(cols) and n.name in TABLE_PARTS:
                    # Alike, but a column came or went: its cells are not under
                    # the same headers, so they follow the plan like any row.
                    inner, ch, _, o_in = _diff_children(
                        o.children, n.children, n.name, images, inner_mode, cols=cols
                    )
                    out.append(n.around(inner))
                    changed |= ch
                    inplace |= o_in
                else:
                    out.append(n.raw())
            continue
        if step[0] in ("into", "outof"):
            # One block is a wrapper (a div) around the other: the wrapper is
            # drawn only on its own side's page.
            o, n = step[1], step[2]
            into = step[0] == "into"
            inner, ch, o_own, o_in = _diff_children(
                [o] if into else o.children,
                n.children if into else [n],
                n.name if into else parent,
                images,
                inner_mode,
            )
            if into and blocks == "inter":
                inner = n.around(inner)
            out.append(inner)
            changed |= ch
            own |= o_own
            inplace |= o_in
        elif step[0] == "pair":
            o, n = step[1], step[2]
            if n.kind == "run":
                both, old_h, new_h, ch = _word_parts(o.tokens, n.tokens, images)
                sides = {"both": (n, both), "old": (o, old_h)}
                side, text = sides.get(runs, (n, new_h))
                out.append(side._run(text))
                changed |= ch
                own |= ch
                inplace |= ch
            elif n.void:
                if blocks != "none":
                    out.append(n.raw())
            else:
                if blocks == "none":
                    continue  # a block is not part of an old copy's own words
                if rows and blocks == "inter" and n.name in TINT_BLOCKS:
                    # A line draws the old words in its old copy, and the new
                    # words in its new copy.
                    new_in, ch, o_own, o_in = _diff_children(
                        o.children, n.children, n.name, images, NEW_MIXED
                    )
                    if o_own:
                        old_in = _diff_children(
                            o.children, n.children, n.name, images, OLD_OWN
                        )[0]
                        out.append(_edit_copies(o, n, old_in, new_in))
                    else:
                        out.append(n.around(new_in))
                else:
                    # An edited block or a container: drawn once, the words
                    # of both sides in it.
                    # A table's columns come from its header rows; its rows,
                    # and their cells, follow them.
                    sub = _table_columns(o, n) if n.name == "table" else None
                    if n.name in TABLE_PARTS and n.name != "table":
                        sub = cols
                    inner, ch, _, o_in = _diff_children(
                        o.children, n.children, n.name, images, inner_mode, cols=sub
                    )
                    out.append(n.around(inner))
                changed |= ch
                inplace |= o_in
        else:
            wrapper = "ins" if step[0] == "ins" else "del"
            node = step[1]
            is_run = node.kind == "run"
            side = "new" if wrapper == "ins" else "old"
            shown = runs in ("both", side) if is_run else blocks == "inter"
            if node.visible():
                if shown:
                    out.append(
                        _render_whole(node, wrapper, blocks == "inter", images, cols)
                    )
                changed = True
                own |= is_run
            elif shown and wrapper == "ins":
                out.append(node.raw())  # markup with nothing to read
            elif shown and node.kind == "el" and node.name in CELL_TAGS:
                # A removed empty cell still holds its column (with its
                # colspan): the values after it stay under their headers.
                out.append(_render_whole(node, "del", blocks == "inter", images))
    return "".join(out), changed, own, inplace


def diff_content(old, new, images=None):
    """Diff two content-HTML strings: blocks first, then words inside each.

    See the header: the blocks of each page are aligned, similar blocks inside a
    replaced stretch are paired, and the words of each pair are diffed. Markup
    that does not nest into blocks gets the plain word diff.

    `images`, if given, is a callable `images(side, src)` returning a digest of
    the file an `<img>` points to (equal for equal bytes; None if unknown),
    side being "old" or "new". An image whose digest differs between the pages
    under the same name is shown as the old one struck and the new one added.
    If it also has a `before_url(src)` method, that URL is what shows the old
    image (the old file is not served where the new one is).
    """
    # Both sides are made safe here, so a page outside the workspace cannot skip
    # it; then each pass swaps its units out, whole, for the diff.
    old, new = sanitize_fragment(old, ids=True), sanitize_fragment(new, ids=True)
    stores = []
    for unit in passes():
        old, old_store = unit.extract(old, "old", images)
        new, new_store = unit.extract(new, "new", images)
        old = unit.tie(old, new, old_store, new_store)
        stores.append((unit, {**old_store, **new_store}))
    # The old copy carries no ids, in its blocks or inside them (the new page
    # owns them); `drop_id_attrs` is also what equal markup ignores.
    a = [
        (kind, drop_id_attrs(text) if kind == "tag" else text)
        for kind, text in tokenize(old)
    ]
    b = tokenize(new)
    tree_a, tree_b = parse_blocks(a, drop_ids=True), parse_blocks(b)
    if tree_a is None or tree_b is None:
        body, _, _, changed = _word_parts(a, b, images)
    else:
        body, changed, _, _ = _diff_children(
            tree_a.children, tree_b.children, "", images
        )
        body += tree_b.tail
    for unit, store in reversed(stores):
        body = unit.restore(body, store, images)
    return body, changed


_LINE_TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]")
_LINE_OPEN_RE = re.compile(
    r'<div class="wc-ln(?: wc-(?:block|edit)-(added|removed|new|old))?" data-k="[0-9a-f]+">'
)


def _line_node(text):
    """One source line as a block of kind `wc-ln`: its text is a run of tokens,
    whitespace included (indentation is a change), a blank line one visible
    token (so adding or removing it is a change). The line's hash in its open
    tag makes only an identical line equal."""
    toks = [("word", html.escape(t, quote=False)) for t in _LINE_TOKEN_RE.findall(text)]
    k = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    node = _Node("el", name="wc-ln", open_=f'<div class="wc-ln" data-k="{k}">')
    node.close = "</div>"
    run = _Node("run", tokens=toks if text.strip() else [("word", "\xa0")])
    run._key = k  # the exact text: a change of indentation is a change
    node.children = [run]
    return node


def source_diff(old_text, new_text):
    """HTML diff of two texts, a line being the unit: the same two steps as
    `diff_content` (align lines and pair similar ones, then diff the words of
    each pair) through the same `_diff_children`, with line numbers (old and
    new, in `data-o` / `data-n`). Wrap it in `.wc-scope`; `FOLD_JS` folds the
    unchanged lines of the `.wc-src` it returns."""
    olds = [_line_node(t) for t in old_text.splitlines()]
    news = [_line_node(t) for t in new_text.splitlines()]
    body = _diff_children(olds, news, "", rows=True)[0]
    o = n = 0

    def number(m):
        # An old row (a removed line, or the old copy of an edited one) has only
        # its old number, a new row only its new number, as in GitHub's unified view.
        nonlocal o, n
        has_old, has_new = (
            m.group(1) not in ("added", "new"),
            m.group(1)
            not in (
                "removed",
                "old",
            ),
        )
        o, n = o + has_old, n + has_new
        old_no = f' data-o="{o}"' if has_old else ""
        new_no = f' data-n="{n}"' if has_new else ""
        return m.group(0)[:-1].rsplit(" data-k", 1)[0] + old_no + new_no + ">"

    return f'<div class="wc-src">{_LINE_OPEN_RE.sub(number, body)}</div>'


def gap_joins_marks(*gaps):
    """Whether a gap between two changed spans is only whitespace, so the spans
    read as one mark. Each gap is a list of `(kind, text)` tokens (the gap on
    the old side, on the new side); a tag or a word in any of them keeps the
    marks apart. The one place this is decided: `_join_marks` for the pages and
    deck-review.py's `mark_words` for the slides both call it."""
    return all(kind in ("space", "ws") for gap in gaps for kind, _ in gap)


def _join_marks(opcodes, a, b):
    """Fold a gap of only whitespace between two changed spans into one span
    when both insert or both remove, so a changed phrase is one mark, as on
    GitHub, not a row of word chips. A gap holding a tag or a word stays."""
    out = []
    for op in opcodes:
        if len(out) >= 2 and op[0] != "equal":
            prev, gap = out[-2], out[-1]
            if (
                prev[0] != "equal"
                and gap[0] == "equal"
                and gap_joins_marks(a[gap[1] : gap[2]], b[gap[3] : gap[4]])
                and (
                    (prev[2] > prev[1] and op[2] > op[1])  # both remove
                    or (prev[4] > prev[3] and op[4] > op[3])  # both insert
                )
            ):
                out[-2:] = [("replace", prev[1], op[2], prev[3], op[4])]
                continue
        out.append(op)
    return out


ALIGN_CANDIDATES = 1_000_000  # candidate matches the exact aligner may weigh


def _runs(keys):
    """The keys with each run of equal neighbours as one, and where each run
    starts in `keys` (plus its end)."""
    runs, starts = [], []
    for i, key in enumerate(keys):
        if not runs or runs[-1] != key:
            runs.append(key)
            starts.append(i)
    return runs, starts + [len(keys)]


def _expand_runs(opcodes, sa, sb):
    """Opcodes over runs, as opcodes over the keys the runs came from."""
    out = []
    for op, i1, i2, j1, j2 in opcodes:
        if op != "equal":
            out.append((op, sa[i1], sa[i2], sb[j1], sb[j2]))
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            a0, a1, b0, b1 = sa[i], sa[i + 1], sb[j], sb[j + 1]
            both = min(a1 - a0, b1 - b0)
            out.append(("equal", a0, a0 + both, b0, b0 + both))
            if a1 - a0 > both:
                out.append(("delete", a0 + both, a1, b0 + both, b0 + both))
            elif b1 - b0 > both:
                out.append(("insert", a0 + both, a0 + both, b0 + both, b1))
    return out


def _align(a, b):
    """difflib opcodes for two lists of keys, with the work bound.

    SequenceMatcher without autojunk is quadratic; a local edit to a large page
    (a slide deck, a long run of blocks) only needs the span between the common
    ends. A long, highly repetitive middle can remain, so its candidate matches
    are counted before the exact matcher is allowed. Over the bound, runs of
    equal neighbours (a generated page's identical rows) are matched as one item
    each; if the middle is still over it, the matcher's popular-item heuristic
    keeps the case responsive, at the cost of coarser alignment inside that
    span. Words and blocks both align through here.
    """
    lo = 0
    while lo < min(len(a), len(b)) and a[lo] == b[lo]:
        lo += 1
    hi = 0
    while hi < min(len(a), len(b)) - lo and a[-1 - hi] == b[-1 - hi]:
        hi += 1
    a_middle, b_middle = a[lo : len(a) - hi], b[lo : len(b) - hi]
    a_counts, b_counts = Counter(a_middle), Counter(b_middle)
    candidates = sum(count * b_counts[key] for key, count in a_counts.items())
    (runs_a, sa), (runs_b, sb) = _runs(a_middle), _runs(b_middle)
    if candidates > ALIGN_CANDIDATES and (
        len(runs_a) < len(a_middle) or len(runs_b) < len(b_middle)
    ):
        middle = _expand_runs(_align(runs_a, runs_b), sa, sb)
    else:
        sm = difflib.SequenceMatcher(
            None, a_middle, b_middle, autojunk=candidates > ALIGN_CANDIDATES
        )
        middle = sm.get_opcodes()
    opcodes = [
        (op, i1 + lo, i2 + lo, j1 + lo, j2 + lo) for op, i1, i2, j1, j2 in middle
    ]
    if lo:
        opcodes.insert(0, ("equal", 0, lo, 0, lo))
    if hi:
        opcodes.append(("equal", len(a) - hi, len(a), len(b) - hi, len(b)))
    return opcodes


def _word_parts(a, b, images=None):
    """Word-level diff of two token lists; returns (both, old, new, changed).

    `both` has the removed and the added words in one run (`<del>` then `<ins>`);
    `old` is the old text only, its removed words in `<del>`; `new` is the new
    text only, its added words in `<ins>`. `changed` is set only for what a
    reader sees: words, inline pairs, a link or image target, a regenerated
    image. Formatting alone (em -> strong) is kept in the new page's markup but
    is not a change."""
    # Align on the visible string of each token.
    opcodes = _align([_align_key(t) for t in a], [_align_key(t) for t in b])
    opcodes = _join_marks(opcodes, a, b)
    out, old_out, new_out = [], [], []
    changed = False
    for op, i1, i2, j1, j2 in opcodes:
        if op == "equal":
            for k in range(i2 - i1):
                old_tok, new_tok = a[i1 + k][1], b[j1 + k][1]
                bare = drop_id_attrs(new_tok)  # (the old tag has no ids)
                if old_tok == bare or b[j1 + k][0] != "tag":
                    out.append(new_tok)  # (equal, but for a tag's digest or spacing)
                    old_out.append(old_tok)
                    new_out.append(new_tok)
                elif pic := next(
                    filter(
                        None, (u.changed(old_tok, new_tok, images) for u in passes())
                    ),
                    None,
                ):
                    changed = True  # same name, different file: before and after
                    out.append(pic[0] + pic[1])
                    old_out.append(pic[0])
                    new_out.append(pic[1])
                elif _DIGEST_RE.sub("", old_tok) == _DIGEST_RE.sub("", bare):
                    out.append(new_tok)
                    old_out.append(old_tok)
                    new_out.append(new_tok)
                else:  # same tag, different link target: its text is marked
                    changed = True
                    out.append(_mark_target(old_tok, new_tok))
                    old_out.append(_mark_old_target(_DIGEST_RE.sub("", old_tok)))
                    new_out.append(_mark_target(old_tok, new_tok))
        else:
            if op in ("delete", "replace"):
                html_, marked = _emit(a[i1:i2], "del", images=images)
                out.append(html_)
                old_out.append(_emit(a[i1:i2], "del", keep_tags=True, images=images)[0])
                changed |= marked
            if op in ("insert", "replace"):
                html_, marked = _emit(b[j1:j2], "ins")
                out.append(html_)
                new_out.append(html_)
                changed |= marked
    return "".join(out), "".join(old_out), "".join(new_out), changed


# Chrome for the diff scaffolding (header, TOC, per-page section banners) and
# the added/removed highlighting. This is layered *after* the site theme when
# one is available, so it only styles our own wrapper classes and the
# <ins>/<del> runs — the page content keeps the site's real typography, colors,
# code highlighting, and dark/light palette.
#
# Highlight colors: a solid green background for added text and a solid red
# background + strikethrough for removed text, the channels GitHub uses for
# word-level diffs, in shades chosen against Asta's light and dark pages (one
# palette, no per-theme switch beyond the dark one). We deliberately do NOT underline insertions:
# in an additive document (a growing survey) almost every run is an insertion, so
# underlining them all paints the page with lines and drowns out any other
# underline cue — including an evidence claim's own dotted underline. Removed
# text keeps its strikethrough (a sparse, meaningful cue that also gives
# color-blind reviewers a non-color signal on the del side). Insertions use a
# slim leading edge instead of an underline, so they remain identifiable without
# recreating the field of horizontal lines that obscured evidence claims.
# The dark shades, the variables of `.wc-scope` in dark mode.
_DARK = """{ --wc-ins-bg: #1b4d0f; --wc-ins-line: #8ee04f;
  --wc-del-bg: #6b1f22; --wc-del-line: #ff7b72;
  --wc-ins-blk: #123a0e; --wc-del-blk: #4a171b;
  --wc-changed: #58a6ff; --wc-new: #8ee04f;
  --wc-removed: #ff7b72; --wc-tag-fg: #0d1117; }"""
# In a dark source view each line is tinted (`--wc-*-blk`), so the changed words
# take a deeper shade than the rendered pages' (those have no line tint, and
# their links need the darker word marks to keep 4.5:1): at least 1.5:1 off the
# line, light text on them still above 4.5:1.
_DARK_SRC = """{ --wc-ins-bg: #2a6b1a; --wc-del-bg: #8e2a2e; }"""
# Greys of a page with no theme to borrow from (the standalone fallback only).
_DARK_GREYS = """{ --wc-hover: rgba(88,166,255,.12);
  --wc-muted: #8b949e; --wc-border: #30363d; }"""

# The tags the stylesheet draws as a figure: those of the figure entries.
_FIGURES = ":is(" + ", ".join(FIGURE_TAGS) + ")"
# The parent of a changed figure's old and new: a paragraph, div or figure whose
# only children are the two units.
_PAIR = (
    ":is(p, div, figure)"
    f":has(> del.wc-unit > {_FIGURES})"
    f":has(> ins.wc-unit > {_FIGURES})"
    ":not(:has(> :not(:is(del, ins).wc-unit)))"
)

# The units drawn framed: one holding a display equation, a figure, a drawing or
# a diagram's text (a code block, a div or a figure of a drawing cell).
_FRAMED = ':has(mjx-container[display="true"]), :has(> :is(img, svg, pre, div, figure))'

# A block that holds only a framed unit (`:has` cannot hold another `:has`).
_UNIT = ":is(del, ins).wc-unit:only-child"
_FRAMED_ONLY = (
    f":has(> {_UNIT} > :is(img, svg, pre, div, figure)), "
    f':has(> {_UNIT} mjx-container[display="true"])'
)

DIFF_STYLE = (
    """
/* Two solid shades of each colour, chosen against Asta's light and dark pages:
   the light one fills a block, the darker one only the words changed. Removed
   is red, added is green. */
.wc-scope { --wc-ins-bg: #b4e4a0; --wc-ins-line: #2a7a12;
            --wc-del-bg: #f7b9b1; --wc-del-line: #c41d2c;
            --wc-ins-blk: #dcf2d0; --wc-del-blk: #fcdad5;
            --wc-changed: #0969da; --wc-new: #2a7a12;
            --wc-removed: #c41d2c; --wc-tag-fg: #fff;
            /* Everything that is not a shade of the diff is the site's: its
               rule colour, its muted text, a wash of its own text colour. */
            --wc-border: var(--bs-border-color, #d0d7de);
            --wc-muted: var(--bs-secondary-color,
                            color-mix(in srgb, currentColor 70%, transparent));
            --wc-strip: color-mix(in srgb, var(--wc-changed) 16%, transparent);
            --wc-strip-line: color-mix(in srgb, var(--wc-changed) 45%, transparent);
            --wc-hover: color-mix(in srgb, currentColor 12%, transparent); }
.wc-scope.wc-standalone { --wc-border: #d0d7de; --wc-muted: #57606a;
            --wc-hover: rgba(9,105,218,.08); }
/* Follow the mode the site is shown in (`data-wc-mode`, set by MODE_JS) when a
   theme is reused. The media query is only for standalone output. */
[data-wc-mode="dark"] .wc-scope {DARK}
@media (prefers-color-scheme: dark) { .wc-scope.wc-standalone {DARK} .wc-scope.wc-standalone {GREYS} }
[data-wc-mode="dark"] .wc-scope .wc-src {DARKSRC}
@media (prefers-color-scheme: dark) { .wc-scope.wc-standalone .wc-src {DARKSRC} }
/* What changed reads wider than a page of prose: its main content takes up to
   1040px (old and new side by side need the room), centred. */
.wc-scope.page-columns { display: block; }
.wc-scope main.content { max-width: 1040px; margin-inline: auto; padding-inline: 1rem; }
.wc-scope header.diff-head { padding: 1.25rem 0 0.5rem; margin-bottom: 1rem;
    border-bottom: 1px solid var(--wc-border); }
.wc-scope header.diff-head h1 { margin: 0 0 .25rem; }
.wc-scope header.diff-head p, .wc-scope .legend, .wc-scope .empty {
    color: var(--wc-muted); }
.wc-scope .legend { font-size: .9rem; }
.wc-scope .legend ins, .wc-scope .legend del { padding: 0 .25em; }
.wc-scope .empty { font-style: italic; }
.wc-scope .wc-note { margin: .25rem 0 .5rem; }
.wc-scope .wc-preview { color: var(--wc-muted); font-size: .95rem;
    padding: .5rem .85rem; border-left: 3px solid var(--wc-border);
    white-space: pre-wrap; overflow-wrap: break-word; }
/* The paper's own viewer, as on its page: one bar over the PDF, a page tall
   at the column's width (whatever the window), and ⤢ for the whole window. */
.wc-scope .paper-view { margin-top: .5rem; }
.wc-scope .paper-bar { display: flex; flex-wrap: wrap; align-items: center;
    gap: .25rem .9rem; font-size: .9rem; padding: .35rem 0;
    border-bottom: 1px solid var(--wc-border); }
.wc-scope .paper-title { font-size: 1rem; }
.wc-scope .paper-expand, .wc-scope .paper-modes button { font: inherit; line-height: 1.2;
    padding: .2rem .55rem; border: 1px solid var(--wc-border); border-radius: 6px;
    background: transparent; color: inherit; cursor: pointer; }
.wc-scope .paper-file { font-size: .8rem; opacity: .75; background: none; padding: 0; }
.wc-scope .paper-modes { display: inline-flex; gap: .3rem; margin-left: auto; }
.wc-scope .paper-expand { margin-left: auto; }
.wc-scope .paper-modes ~ .paper-expand { margin-left: 0; }
.wc-scope .paper-modes button { font-size: .85rem; padding: .15rem .7rem; }
.wc-scope .paper-modes button[aria-pressed="true"] { font-weight: 600;
    background: var(--bs-body-color, #24292f); color: var(--bs-body-bg, #fff);
    border-color: var(--bs-body-color, #24292f); }
.wc-scope .paper-view object { display: block; width: 100%; aspect-ratio: 3 / 4; border: 0; }
.wc-scope .paper-view.paper-full { position: fixed; inset: 0; z-index: 1050; margin: 0;
    display: flex; flex-direction: column; background: var(--bs-body-bg, #fff); }
.wc-scope .paper-full .paper-bar { padding: .35rem .75rem; }
.wc-scope .paper-full object { flex: 1; aspect-ratio: auto; }
.wc-scope nav.toc { font-size: .95rem; margin: 0 0 2rem; padding: .75rem 1rem;
    border: 1px solid var(--wc-border); border-radius: 6px; }
.wc-scope nav.toc .toc-head { margin: 0 0 .35rem; font-weight: 600; }
.wc-scope nav.toc ul { margin: 0; padding-inline-start: 1.2rem; }
.wc-scope nav.toc li { margin: .15rem 0; }
.wc-scope nav.toc .toc-file { font-size: .8rem; opacity: .75; background: none; padding: 0; }
.wc-scope nav.toc .toc-count { color: var(--wc-muted); }
.wc-scope section.page-diff { margin-top: 2.5rem; padding: .75rem 1rem 1rem;
    border: 1px solid var(--wc-border); border-left: 4px solid var(--wc-changed);
    border-radius: 6px; }
.wc-scope section.page-diff.new { border-left-color: var(--wc-new); }
.wc-scope section.page-diff.removed { border-left-color: var(--wc-removed); }
.wc-scope section.page-diff > h2 { margin-top: .25rem; }
.wc-scope .tag { font-weight: 600;
    padding: .15em .6em; border-radius: 1em; vertical-align: middle;
    margin-left: .5em; color: var(--wc-tag-fg); }
.wc-scope section.page-diff > h2 .tag { font-size: .65em; }
.wc-scope nav.toc .tag { font-size: .75em; }
.wc-scope .tag.changed { background: var(--wc-changed); color: var(--wc-tag-fg); }
.wc-scope .tag.new { background: var(--wc-new); color: var(--wc-tag-fg); }
.wc-scope .tag.removed { background: var(--wc-removed); color: var(--wc-tag-fg); }
.wc-scope .diff-body { overflow-wrap: break-word; }
.wc-scope ins { background: var(--wc-ins-bg);
    text-decoration: none; border-inline-start: 2px solid var(--wc-ins-line);
    border-radius: 2px; padding: 0 .1em; }
.wc-scope del { background: var(--wc-del-bg);
    text-decoration: line-through; text-decoration-color: var(--wc-del-line);
    text-decoration-thickness: 2px; border-radius: 2px; padding: 0 .1em; }
/* Block level: a wholly removed or added block (`wc-block-removed` /
   `wc-block-added`) is the light shade only. An edited block has none, only its
   words are marked; the exception is a source line, drawn twice, its old copy
   (`wc-edit-old`) in the light red, then its new copy (`wc-edit-new`) in the
   light green, as GitHub's source view. Unchanged blocks have no shade. */
.wc-scope :is(.wc-edit-old, .wc-block-removed):not(tr) { background: var(--wc-del-blk); }
.wc-scope :is(.wc-edit-new, .wc-block-added):not(tr) { background: var(--wc-ins-blk); }
/* A row is shaded through its cells, as a layer over whatever fill the theme's
   table gives them (Bootstrap fills cells, which would hide a row background). */
.wc-scope tr.wc-block-removed > :is(td, th) {
    background-image: linear-gradient(var(--wc-del-blk), var(--wc-del-blk)); }
.wc-scope tr.wc-block-added > :is(td, th) {
    background-image: linear-gradient(var(--wc-ins-blk), var(--wc-ins-blk)); }
/* A wholly added or removed block takes the light shade only: its words are
   not marked darker, nor struck through. */
.wc-scope .wc-block-added ins { background: none; border-inline-start: 0; }
.wc-scope .wc-block-removed del { background: none; text-decoration: none; }
/* A whole unit is shaded like any other change when it is not framed below
   (an inline equation takes the darker word shade, as words do); no band behind
   an image, no outline or fading on it. */
.wc-scope del.wc-unit, .wc-scope ins.wc-unit { padding: .1em .3em; border-radius: 4px;
    text-decoration: none; border-inline-start: 0; outline: none; }
.wc-scope del.wc-unit { background: var(--wc-del-blk); }
.wc-scope ins.wc-unit { background: var(--wc-ins-blk); }
.wc-scope del.wc-unit:has(> mjx-container:not([display="true"])) { background: var(--wc-del-bg); }
.wc-scope ins.wc-unit:has(> mjx-container:not([display="true"])) { background: var(--wc-ins-bg); }
/* A whole display equation, figure or diagram is framed, never filled, as
   GitHub's image diff frames old and new: on the page's own background, the old
   in a thin red frame, the new in a thin green one, each with a small "Before"
   or "After" label in its colour. A block that holds only such a unit has no
   shade either: the frame says old or new. */
.wc-scope del.wc-unit { --wc-frame: var(--wc-del-line); --wc-label: "Before"; }
.wc-scope ins.wc-unit { --wc-frame: var(--wc-ins-line); --wc-label: "After"; }
.wc-scope :is(del, ins).wc-unit:is({FRAMED}) {
    display: block; background: transparent; text-decoration: none;
    border: 1px solid var(--wc-frame); border-radius: 6px; padding: .45rem .6rem .6rem; }
.wc-scope :is(del, ins).wc-unit:is({FRAMED})::before {
    display: block; content: var(--wc-label); color: var(--wc-frame); text-align: left;
    font: 600 .72rem/1.3 system-ui, sans-serif; letter-spacing: .02em;
    margin-bottom: .3rem; text-decoration: none; }
.wc-scope :is(.wc-edit-old, .wc-block-removed, .wc-edit-new, .wc-block-added):not(tr):is({FRAMED_ONLY}) {
    background: transparent; }
.wc-scope .wc-unit > {FIGURES} { max-width: 100%; height: auto; }
/* A changed figure or drawing: old and new side by side, as GitHub's
   image diff shows them, when their parent holds nothing else (else old above
   new, so that a page is never set in a row). */
.wc-scope {PAIR} {
    display: flex; gap: 1rem; align-items: flex-start; }
.wc-scope {PAIR} > .wc-unit {
    flex: 1 1 0; min-width: 0; }
.wc-scope {PAIR} > .wc-unit > {FIGURES} {
    width: 100%; }
/* A pair whose figure is wider, at its natural size, than half the column is
   set old above new (the page's script marks it; the figure takes its natural
   width, up to the full column). */
.wc-scope {PAIR}.wc-pair-stack {
    flex-direction: column; align-items: stretch; }
.wc-scope {PAIR}.wc-pair-stack > .wc-unit {
    flex: none; }
.wc-scope .wc-unit > pre { margin: 0; overflow-x: auto; }
/* A Mermaid diagram: its text wrapped (never cut off at the right) until the
   page draws it, then its drawing at the width of its box. */
.wc-scope pre.mermaid { white-space: pre-wrap; overflow-wrap: anywhere; }
.wc-scope pre.mermaid[data-wc-drawn] { white-space: normal; background: none;
    border: 0; padding: 0; text-align: center; }
.wc-scope pre.mermaid[data-wc-drawn] svg { max-width: 100%; height: auto; }
.wc-scope .wc-img-unavailable { font-style: italic; }
/* A link or image whose target changed: its text takes the dark shade and the
   old target is shown beside the new. */
.wc-scope .wc-link-changed { background: var(--wc-ins-bg); border-radius: 2px; }
.wc-scope .wc-link-was { background: var(--wc-del-bg); border-radius: 2px; }
.wc-scope a.wc-link-changed::after { content: " (" attr(data-wc-was) " \\2192 " attr(href) ")";
    font-size: .8em; color: var(--wc-muted); overflow-wrap: anywhere; }
/* A link taken off words that stay: its old target, where the link began. */
.wc-scope .wc-link-gone { background: none; }
.wc-scope .wc-link-gone::before { content: "(link removed: " attr(data-wc-was) ") ";
    font-size: .8em; background: var(--wc-del-bg);
    border-radius: 2px; overflow-wrap: anywhere; }
.wc-scope img.wc-link-changed { outline: 3px solid var(--wc-ins-line); }
.wc-scope img.wc-link-was { outline: 3px solid var(--wc-del-line); }
/* Formatting put on words that were already there (em -> strong): the new tag
   is outlined, as the words did not change. */
.wc-scope .wc-fmt-changed { outline: 1px dashed var(--wc-changed); outline-offset: 2px; }
/* Links: no resting underline on the diff (GitHub's diff view does the same).
   The reused theme carries Bootstrap's default `a { text-decoration: underline }`,
   which otherwise underlines every citation, crossref (e.g. "Table 1") and bare
   URL in the change — and inside an inserted run those links pick up the green
   ins colour, reading as green underlines scattered across the page. A modest
   weight change keeps a persistent non-colour cue without adding another field
   of lines; the underline returns on hover or keyboard focus. */
.wc-scope a { text-decoration: none; font-weight: 600; }
.wc-scope a:hover, .wc-scope a:focus { text-decoration: underline; }
/* Evidence claims (`.ev`) need a visible cue on the diff. The extension's
   default thin currentColor border is intentionally subtle on a normal
   report, but becomes effectively invisible against the green insertion tint.
   Strengthen it to a 2px dotted rule in the active theme's link color, so it
   stays an underline rather than another background and follows light/dark. */
.wc-scope .wc-ev-chip { font-size: .7em; font-weight: 600; white-space: nowrap;
    color: var(--wc-tag-fg); padding: 0 .3em; border-radius: 3px; }
.wc-scope .wc-ev-chip.wc-ev-add { background: var(--wc-new); }
.wc-scope .wc-ev-chip.wc-ev-del { background: var(--wc-removed); }
.wc-scope .ev { border-bottom: 2px dotted var(--bs-link-color, var(--wc-changed)); }
/* Insertions are background-only: the `ins` rule above sets
   `text-decoration: none` to suppress the browser UA-default `ins {
   text-decoration: underline }` (otherwise every added run keeps a green
   underline even with no explicit underline rule in this stylesheet). */
/* Source, a line being the unit (`source_diff`): the same two rows as the blocks
   above (light on the line, darker on its words), an old row with its old line
   number and a new row with its new one in a gutter, and no strike-through, as
   GitHub's unified view draws it. */
.wc-scope .wc-src { font: .8rem/1.5 var(--bs-font-monospace, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
    border: 1px solid var(--wc-border); border-radius: 6px; overflow: hidden; }
.wc-scope .wc-ln { position: relative; padding: 0 .75rem 0 8.5em; min-height: 1.5em;
    white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; }
.wc-scope .wc-ln::before, .wc-scope .wc-ln::after { position: absolute; top: 0; width: 3.5em;
    text-align: right; color: var(--wc-muted); user-select: none; }
.wc-scope .wc-ln::before { content: attr(data-o); left: .25em; }
.wc-scope .wc-ln::after { content: attr(data-n); left: 4.25em; }
.wc-scope .wc-src ins, .wc-scope .wc-src del { padding: 0; border-inline-start: 0;
    text-decoration: none; }
/* The fold strip, for unchanged lines, blocks and slides alike (`FOLD_JS`, and
   the deck's `details.wc-expander`): one look, a row tinted What changed's own
   blue where the folded ones were, in the page's text colour, with blue
   arrows; the arrows open about 20 at a time from the change above (down) or
   below (up), the text opens all of them. */
.wc-scope [hidden] { display: none !important; }
.wc-scope :is(div, li).wc-strip, .wc-scope .wc-strip-bar, .wc-scope .wc-expander > summary {
    display: flex; align-items: center; gap: .25rem; margin: .5rem 0;
    padding: 2px .5rem; font-size: .85rem; line-height: 1.6;
    color: inherit; background: var(--wc-strip);
    border-block: 1px solid var(--wc-strip-line); }
.wc-scope .wc-expander > summary { cursor: pointer; list-style: none; }
.wc-scope .wc-expander > summary::-webkit-details-marker { display: none; }
.wc-scope .wc-expander > summary:hover { background: var(--wc-hover); }
.wc-scope .wc-expander[open] > summary { margin-bottom: .5rem; }
.wc-scope .wc-strip button:not(.wc-more), .wc-scope .wc-expander-icon {
    color: var(--wc-changed); font-weight: 700; }
.wc-scope li.wc-strip { list-style: none; }
/* In a table body the strip is a row with one cell across; the cell is the
   table's own, so it takes none of the theme's cell padding, rule or fill. */
.wc-scope tr.wc-strip > td { padding: 0; border: 0; background: none;
    box-shadow: none; }
.wc-scope tr.wc-strip .wc-strip-bar { margin: 0; }
.wc-scope .wc-src .wc-strip { margin: 0; border-width: 1px 0; }
.wc-scope .wc-strip button { font: inherit; color: inherit; background: transparent;
    border: 0; border-radius: 4px; padding: 0 .45em; cursor: pointer; }
.wc-scope .wc-strip button:hover { background: var(--wc-hover); }
.wc-scope .wc-strip .wc-more:hover { color: var(--wc-changed); }
.wc-scope .wc-strip .wc-more { margin-inline-start: .25rem; }
.wc-scope .wc-toolbar { margin: -.5rem 0 1.5rem; }
.wc-scope .wc-toolbar button { font: inherit; font-size: .85rem; cursor: pointer;
    color: var(--wc-changed); background: transparent; padding: .35em .9em;
    border: 1px solid var(--wc-border); border-radius: 6px; }
.wc-scope .wc-toolbar button:hover { border-color: var(--wc-changed); }
""".replace("{DARKSRC}", _DARK_SRC)
    .replace("{FRAMED_ONLY}", _FRAMED_ONLY)
    .replace("{FRAMED}", _FRAMED)
    .replace("{PAIR}", _PAIR)
    .replace("{FIGURES}", _FIGURES)
    .replace("{DARK}", _DARK)
    .replace("{GREYS}", _DARK_GREYS)
)

# What the fold strip calls the elements it hides, in a reader's terms ("3
# unchanged paragraphs"): the name of the kind of each tag (`KINDS`), then a few
# finer names a reader uses, by tag and by class.
_STRIP_TAG_NAMES = {"section": "section", "figure": "figure"}
for _kind in KINDS:
    if (
        _kind.role in ("text", "row", "container")
        and _kind.name != "authored edit mark"
    ):
        for _tag in _kind.tags:
            _STRIP_TAG_NAMES.setdefault(_tag, _kind.name)
_STRIP_CLASS_NAMES = {
    "callout": "callout",
    "sourceCode": "code block",
    "quarto-figure": "figure",
    "cell": "cell",
}

# Client-side progressive enhancement: fold runs of unchanged block elements
# (recursively, at every nesting level) and unchanged source lines behind one
# strip, GitHub's, in What changed's blue: "⋯ 3 unchanged paragraphs" (or "12
# unchanged lines"), with arrows that open about 20 at a time and the text to
# open all. Folded elements are only hidden, never moved or copied, so it
# cannot corrupt markup; with JS off the full content is shown.
FOLD_JS = r"""
(function () {
  "use strict";
  var STEP = 20;         // what one arrow opens
  var MIN_CHARS = 260;   // don't bother folding a small gap of blocks
  var MIN_BLOCKS = 1;    // a rendered block can contain an entire long section
  var CONTEXT = 1;       // unchanged blocks kept visible beside a change
  var MAX_CONTEXT_CHARS = 500; // fold large neighbors instead of treating them as context
  var LINE_CONTEXT = 3;  // source lines kept visible beside a change
  var MIN_LINES = 3;     // fewest source lines worth a strip
  var strips = [];
  var TAG_NAMES = __TAG_NAMES__;
  var CLASS_NAMES = __CLASS_NAMES__;

  // What a hidden run is called in a reader's terms: "3 paragraphs", "2 list
  // items", "3 paragraphs and 1 list item", "12 lines"; past two kinds, "parts".
  function nameOf(el) {
    for (var c in CLASS_NAMES) if (el.classList.contains(c)) return CLASS_NAMES[c];
    return TAG_NAMES[el.tagName.toLowerCase()] || "part";
  }
  function count(n, name) { return n + " " + name + (n === 1 ? "" : "s"); }
  function unchanged(hidden, lines) {
    var counts = {}, order = [];
    hidden.forEach(function (el) {
      var name = lines ? "line" : nameOf(el);
      if (!(name in counts)) { counts[name] = 0; order.push(name); }
      counts[name]++;
    });
    var text = order.length > 2 ? count(hidden.length, "part") :
      order.map(function (name) { return count(counts[name], name); }).join(" and ");
    return text.replace(" ", " unchanged ");
  }

  // Be conservative about where we insert the block-level strip. A denylist is
  // unsafe here: besides tables/lists, phrasing-only containers such as
  // paragraphs, headings, and summaries cannot contain one. Unknown containers
  // are therefore traversal-only. This allowlist covers the ordinary
  // flow-content containers emitted by Quarto in which a strip is valid. A list
  // and a table body take a strip of their own kind (`stripFor`): a div is not
  // a valid child of either.
  var FOLD_CONTAINERS = { BODY: 1, DIV: 1, MAIN: 1, ARTICLE: 1, SECTION: 1,
    NAV: 1, ASIDE: 1, HEADER: 1, FOOTER: 1, BLOCKQUOTE: 1, FIGURE: 1,
    FIGCAPTION: 1, LI: 1, DD: 1, TD: 1, TH: 1, UL: 1, OL: 1, TBODY: 1,
    THEAD: 1, TFOOT: 1 };
  var ROW_GROUPS = { TBODY: 1, THEAD: 1, TFOOT: 1 };

  // Out-of-flow or hidden subtrees — an absolutely-positioned hover popover /
  // tooltip, a display:none or visibility:hidden aside — are not part of the
  // readable diff flow. Folding their "unchanged" inner blocks is pointless and
  // corrupting: e.g. an inline hover-popover attached to a claim would have its
  // quote folded away until the reader hovers. Skip such subtrees entirely
  // (don't recurse into them, never fold them).
  function inFlow(el) {
    var view = el.ownerDocument.defaultView;
    var s = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
    if (!s) return true;
    if (s.display === "none" || s.visibility === "hidden") return false;
    if (s.position === "absolute" || s.position === "fixed") return false;
    return true;
  }
  // Every mark the engine puts on a change: words (ins, del), the old and new
  // copy of an edited block, an added or removed block, a changed link target or
  // formatting, a claim's evidence gained or lost. An edit with no word marks
  // (a link's href) is still an edit.
  var CHANGE = "ins, del, .wc-edit-old, .wc-edit-new, .wc-block-added, " +
    ".wc-block-removed, .wc-link-was, .wc-link-changed, .wc-fmt-changed, " +
    ".wc-ev-chip";
  function hasChange(el) {
    return el.matches(CHANGE) || !!el.querySelector(CHANGE);
  }
  function button(bar, label, title, onclick) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = title;
    b.addEventListener("click", onclick);
    bar.appendChild(b);
    return b;
  }
  // The strip's element and the one the buttons go in: an li in a list, a row
  // with one cell across the table in a table body, a div anywhere else.
  function stripFor(container) {
    var tag = container.tagName;
    var bar = document.createElement(tag === "UL" || tag === "OL" ? "li" :
      ROW_GROUPS[tag] ? "tr" : "div");
    bar.className = "wc-strip";
    if (!ROW_GROUPS[tag]) return { bar: bar, host: bar };
    var width = 1;
    Array.prototype.forEach.call(container.children, function (row) {
      var n = 0;
      Array.prototype.forEach.call(row.children, function (cell) {
        n += parseInt(cell.getAttribute("colspan"), 10) || 1;
      });
      width = Math.max(width, n);
    });
    var cell = document.createElement("td");
    cell.setAttribute("colspan", String(width));
    var inner = document.createElement("div");
    inner.className = "wc-strip-bar";
    cell.appendChild(inner);
    bar.appendChild(cell);
    return { bar: bar, host: inner };
  }
  // Hide `run` (sibling elements) behind one strip placed where they were.
  // `above` / `below`: a change sits next to the run on that side, so the arrow
  // that opens from it is offered.
  function collapse(container, run, lines, above, below) {
    var hidden = run.slice();
    var made = stripFor(container);
    var bar = made.bar;
    var down = button(made.host, "↓", "Show " + STEP + " more below the change above",
      function () { open(hidden.splice(0, STEP)); });
    var up = button(made.host, "↑", "Show " + STEP + " more above the change below",
      function () { open(hidden.splice(-STEP)); });
    var more = button(made.host, "", "Show all", function () { open(hidden.splice(0)); });
    more.className = "wc-more";
    function show() {
      var n = hidden.length;
      more.textContent = "⋯ " + unchanged(hidden, lines);
      down.hidden = !above;
      up.hidden = !below;
      if (n) container.insertBefore(bar, hidden[0]);
      else bar.remove();
    }
    function open(els) {
      els.forEach(function (el) { el.hidden = false; });
      show();
    }
    strips.push({
      all: function () { open(hidden.splice(0)); },
      fold: function () {
        run.forEach(function (el) { el.hidden = true; });
        hidden = run.slice();
        show();
      }
    });
    strips[strips.length - 1].fold();
  }
  // Hidden items are not counted by an ordered list, so the item that follows a
  // folded run says its own number.
  function numberAfter(list, kids, at) {
    if (list.tagName !== "OL" || at >= kids.length) return;
    var reversed = list.hasAttribute("reversed");
    var start = parseInt(list.getAttribute("start"), 10);
    if (isNaN(start)) start = reversed ? kids.length : 1;
    kids[at].setAttribute("value", String(reversed ? start - at : start + at));
  }
  function fold(container) {
    var kids = Array.prototype.slice.call(container.children);
    if (!kids.length) return;
    var lines = container.classList.contains("wc-src");
    var changed = kids.map(hasChange);
    var flow = kids.map(inFlow);
    var keep = kids.map(function () { return false; });
    kids.forEach(function (el, k) {
      if (!changed[k]) return;
      var around = lines ? LINE_CONTEXT : CONTEXT;
      for (var j = Math.max(0, k - around);
           j <= Math.min(kids.length - 1, k + around); j++) {
        // Rendered blocks are not source lines: a single sibling can contain a
        // whole section. Keep compact neighbors as context, but fold large ones.
        keep[j] = changed[j] || lines ||
          kids[j].textContent.length <= MAX_CONTEXT_CHARS;
      }
    });
    // Out-of-flow/hidden children are never folded and act as run boundaries.
    // (After the context pass so it can't be undone by a neighbor's window.)
    kids.forEach(function (el, k) { if (!flow[k]) keep[k] = true; });
    // Recurse into changed, in-flow containers before folding sibling runs — but
    // never into an <ins>/<del> wrapper. Those wrap a run of inserted/deleted
    // inline content, inside which nothing is "unchanged"; recursing there makes
    // hasChange() see every child as unchanged (no ins/del *descendant*) and fold
    // real inserted text — e.g. hiding a claim's hover-popover quote behind a
    // bogus "N unchanged blocks" strip.
    kids.forEach(function (el, k) {
      if (changed[k] && flow[k] && el.children.length && !lines &&
          el.tagName !== "INS" && el.tagName !== "DEL") fold(el);
    });
    // Only fold sibling runs where a block-level strip is a valid child. Still
    // recurse through other containers so a changed table cell or list item can
    // fold its own flow-content children.
    if (!FOLD_CONTAINERS[container.tagName]) return;
    var start = 0;
    while (start < kids.length) {
      if (keep[start]) { start++; continue; }
      var end = start;
      while (end < kids.length && !keep[end]) end++;
      var run = kids.slice(start, end);
      var chars = run.reduce(function (a, el) { return a + el.textContent.length; }, 0);
      if (lines ? run.length >= MIN_LINES
                : run.length >= MIN_BLOCKS && chars >= MIN_CHARS) {
        numberAfter(container, kids, end);
        collapse(container, run, lines, start > 0, end < kids.length);
      }
      start = end;
    }
  }
  var allOpen = false;
  function setAll(open) {
    allOpen = open;
    strips.forEach(function (s) { open ? s.all() : s.fold(); });
  }
  function addToolbar() {
    if (!strips.length) return;
    var anchor = document.querySelector("section.page-diff");
    if (!anchor) return;
    var bar = document.createElement("div");
    bar.className = "wc-toolbar";
    var btn = button(bar, "Expand all unchanged", "", function () {
      setAll(!allOpen);
      btn.textContent = allOpen ? "Collapse all unchanged" : "Expand all unchanged";
    });
    anchor.parentNode.insertBefore(bar, anchor);
  }
  // A wholly added or removed block whose first line hangs out to the left of
  // the rest (a reference: a negative text-indent) is shaded from its padding
  // edge, so the first line would stand on no shade. Grow the block left by the
  // overhang and pad it by the same, so that the text stays where it was and
  // the shade covers the first line too.
  function shadeHanging(root) {
    Array.prototype.forEach.call(
      root.querySelectorAll(".wc-block-added, .wc-block-removed"), function (block) {
        var view = block.ownerDocument.defaultView;
        var s = view && view.getComputedStyle ? view.getComputedStyle(block) : null;
        var hang = s ? parseFloat(s.textIndent) : NaN;
        if (!(hang < 0) || s.display !== "block" || block.hasAttribute("data-wc-hang")) return;
        block.setAttribute("data-wc-hang", "");
        block.style.marginLeft = (parseFloat(s.marginLeft) || 0) + hang + "px";
        block.style.paddingLeft = (parseFloat(s.paddingLeft) || 0) - hang + "px";
      });
  }
  function run() {
    // The workspace page's diff bodies, source views, and any container a page
    // outside the workspace marks with data-wc-fold. A container inside another
    // is folded by the outer one's recursion, not twice.
    var targets = Array.prototype.slice.call(document.querySelectorAll(
      "section.page-diff.changed .diff-body, .wc-src, [data-wc-fold]"));
    targets.filter(function (t) {
      return !targets.some(function (o) { return o !== t && o.contains(t); });
    }).forEach(fold);
    addToolbar();
    shadeHanging(document);
  }
  if (typeof window !== "undefined") window.wcFold = { fold: fold, setAll: setAll };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else { run(); }
})();
""".replace(
    "__TAG_NAMES__", json.dumps(_STRIP_TAG_NAMES, separators=(",", ":"))
).replace("__CLASS_NAMES__", json.dumps(_STRIP_CLASS_NAMES, separators=(",", ":")))


# Body typography for the fallback path, when no site theme could be reused, and
# for a page outside the workspace. Scoped to the wrapper, so it is safe in a page
# that has its own styles: the wrapper brings its own text and background colour,
# light or dark by `prefers-color-scheme`, and wraps long lines at any width.
STANDALONE_STYLE = """
.wc-scope.wc-standalone { font: 16px/1.65 -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, Helvetica, Arial, sans-serif; box-sizing: border-box;
    max-width: 60rem; margin-inline: auto; padding: 0 1.5rem 4rem;
    color-scheme: light dark; color: #1b1b1b; background: #fff;
    overflow-wrap: anywhere; }
.wc-scope.wc-standalone *, .wc-scope.wc-standalone *::before,
.wc-scope.wc-standalone *::after { box-sizing: inherit; }
.wc-scope.wc-standalone :is(img, svg, video, canvas) { max-width: 100%; height: auto; }
.wc-scope.wc-standalone :is(pre, code) { white-space: pre-wrap; overflow-wrap: anywhere; }
.wc-scope.wc-standalone :is(table, td, th) { overflow-wrap: anywhere; }
.wc-scope section.page-diff table { border-collapse: collapse; max-width: 100%; }
.wc-scope section.page-diff td, .wc-scope section.page-diff th {
    border: 1px solid var(--wc-border); padding: .3em .5em; }
@media (prefers-color-scheme: dark) {
  .wc-scope.wc-standalone { background: #0d1117; color: #e6edf3; } }
"""
