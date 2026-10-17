//! Preserve already-present cooperative insertions while deriving a patch.
use similar::Algorithm;
use similar::DiffTag;
use similar::capture_diff_slices;

fn normalise_line(line: &str) -> String {
    line.trim()
        .chars()
        .map(|c| match c {
            '\u{2010}' | '\u{2011}' | '\u{2012}' | '\u{2013}' | '\u{2014}' | '\u{2015}'
            | '\u{2212}' => '-',
            '\u{2018}' | '\u{2019}' | '\u{201A}' | '\u{201B}' => '\'',
            '\u{201C}' | '\u{201D}' | '\u{201E}' | '\u{201F}' => '"',
            '\u{00A0}' | '\u{2002}' | '\u{2003}' | '\u{2004}' | '\u{2005}' | '\u{2006}'
            | '\u{2007}' | '\u{2008}' | '\u{2009}' | '\u{200A}' | '\u{202F}' | '\u{205F}'
            | '\u{3000}' => ' ',
            other => other,
        })
        .collect()
}

fn lines_equivalent(lhs: &str, rhs: &str) -> bool {
    normalise_line(lhs) == normalise_line(rhs)
}

fn find_ordered_alignment(
    original_lines: &[String],
    pattern: &[String],
    start: usize,
) -> Option<Vec<usize>> {
    if pattern.is_empty() {
        return Some(Vec::new());
    }

    let mut alignment = Vec::with_capacity(pattern.len());
    let mut cursor = start;
    for needle in pattern {
        let relative_match = original_lines[cursor..]
            .iter()
            .position(|line| lines_equivalent(line, needle))?;
        let match_index = cursor + relative_match;
        alignment.push(match_index);
        cursor = match_index + 1;
    }

    Some(alignment)
}

/// Track which real source lines came from the baseline or an accepted peer insertion.
pub(crate) struct AugmentedPattern {
    pub(crate) lines: Vec<String>,
    pub(crate) original_indices: Vec<usize>,
    pub(crate) preserved_insertions: Vec<(usize, usize)>,
}

pub(crate) fn augment_pattern_with_target_insertions(
    original_lines: &[String],
    pattern: &[String],
    new_slice: &[String],
    start: usize,
) -> Option<AugmentedPattern> {
    let alignment = find_ordered_alignment(original_lines, pattern, start)?;
    let mut inserted_before = vec![Vec::<String>::new(); pattern.len() + 1];
    let mut inserted_indices = vec![Vec::<usize>::new(); pattern.len() + 1];
    for op in capture_diff_slices(Algorithm::Myers, pattern, new_slice) {
        let (tag, old_range, new_range) = op.as_tag_tuple();
        if tag == DiffTag::Insert {
            inserted_indices[old_range.start].extend(new_range.clone());
            inserted_before[old_range.start].extend_from_slice(&new_slice[new_range]);
        }
    }

    let mut current_before = vec![Vec::<String>::new(); pattern.len() + 1];
    for idx in 1..pattern.len() {
        current_before[idx] = original_lines[alignment[idx - 1] + 1..alignment[idx]].to_vec();
    }

    if let Some(last_alignment) = alignment.last().copied() {
        let trailing_insertions = &inserted_before[pattern.len()];
        let mut cursor = last_alignment + 1;
        while current_before[pattern.len()].len() < trailing_insertions.len()
            && cursor < original_lines.len()
            && lines_equivalent(
                &original_lines[cursor],
                &trailing_insertions[current_before[pattern.len()].len()],
            )
        {
            current_before[pattern.len()].push(original_lines[cursor].clone());
            cursor += 1;
        }
    }

    if !current_before
        .iter()
        .enumerate()
        .any(|(idx, lines)| idx > 0 && !lines.is_empty())
    {
        return None;
    }

    let mut accepted_insertions = vec![Vec::<usize>::new(); pattern.len() + 1];
    for idx in 1..=pattern.len() {
        // Use the same normalized, ordered subsequence match that admits the
        // existing peer lines. Keep the actual source bytes as the anchors.
        accepted_insertions[idx] =
            find_ordered_alignment(&inserted_before[idx], &current_before[idx], 0)?
                .into_iter()
                .map(|offset| inserted_indices[idx][offset])
                .collect();
    }

    let mut augmented = AugmentedPattern {
        lines: Vec::new(),
        original_indices: Vec::with_capacity(pattern.len()),
        preserved_insertions: Vec::new(),
    };
    for (idx, line) in pattern.iter().enumerate() {
        augmented.original_indices.push(augmented.lines.len());
        augmented.lines.push(line.clone());
        for (peer, &new_index) in current_before[idx + 1]
            .iter()
            .zip(&accepted_insertions[idx + 1])
        {
            augmented
                .preserved_insertions
                .push((augmented.lines.len(), new_index));
            augmented.lines.push(peer.clone());
        }
    }

    Some(augmented)
}
