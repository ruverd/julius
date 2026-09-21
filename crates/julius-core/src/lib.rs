use std::collections::HashMap;

fn neutral(line: &str) -> bool {
    if line.len() < 16
        || !line
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || " _.,:;/()-".contains(c))
    {
        return false;
    }
    let lower = line.to_ascii_lowercase();
    !lower.split(|c: char| !c.is_ascii_alphabetic()).any(|word| {
        matches!(
            word,
            "error" | "exception" | "warning" | "denied" | "permission" | "approval"
                | "instruction" | "fail" | "failed" | "failure" | "assert" | "assertion"
                | "panic" | "traceback"
        )
    })
}

fn compress_blocks(lines: &[&str], artifact_id: &str) -> Option<String> {
    // Bounded windows keep this deterministic on large tool outputs. A block must
    // recur at least three times without overlap; its first occurrence stays intact.
    for width in (2..=8.min(lines.len() / 3)).rev() {
        let mut positions: HashMap<Vec<&str>, Vec<usize>> = HashMap::new();
        for start in 0..=lines.len() - width {
            let block = &lines[start..start + width];
            if block.iter().all(|line| neutral(line)) {
                positions.entry(block.to_vec()).or_default().push(start);
            }
        }
        let mut groups: Vec<_> = positions.into_values().collect();
        groups.sort_by_key(|starts| starts[0]);
        for starts in groups {
            let mut disjoint = Vec::new();
            for start in starts {
                if disjoint.last().is_none_or(|last: &usize| start >= *last + width) {
                    disjoint.push(start);
                }
            }
            if disjoint.len() < 3 {
                continue;
            }
            let mut rendered = Vec::with_capacity(lines.len());
            let mut index = 0;
            let mut occurrence = 0;
            while index < lines.len() {
                if occurrence < disjoint.len() && index == disjoint[occurrence] {
                    occurrence += 1;
                    if occurrence == 1 {
                        rendered.extend(lines[index..index + width].iter().map(|s| (*s).to_string()));
                    } else {
                        rendered.push(format!(
                            "[repeated exact block {occurrence}/{}; original lines {}-{}; restore artifact {artifact_id}]",
                            disjoint.len(), disjoint[0] + 1, disjoint[0] + width
                        ));
                    }
                    index += width;
                } else {
                    rendered.push(lines[index].to_string());
                    index += 1;
                }
            }
            return Some(rendered.join("\n"));
        }
    }
    None
}

/// Replace only repeated, exact, neutral text; an external artifact retains the original.
pub fn compress_repeated_lines(content: &str, artifact_id: &str) -> String {
    let lines: Vec<&str> = content.split('\n').collect();
    if let Some(blocks) = compress_blocks(&lines, artifact_id) {
        if blocks.len() < content.len() {
            return blocks;
        }
    }
    let mut counts: HashMap<&str, usize> = HashMap::new();
    for line in &lines {
        if neutral(line) { *counts.entry(line).or_default() += 1; }
    }
    let mut seen: HashMap<&str, usize> = HashMap::new();
    let reduced = lines.iter().map(|line| {
        let count = *counts.get(line).unwrap_or(&0);
        if count < 3 { return (*line).to_string(); }
        let ordinal = seen.entry(line).or_default();
        *ordinal += 1;
        if *ordinal == 1 { (*line).to_string() }
        else { format!("[repeated exact line {ordinal}/{count}; restore artifact {artifact_id}]") }
    }).collect::<Vec<_>>().join("\n");
    if reduced.len() < content.len() { reduced } else { content.to_string() }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn repeated_lines_reduce_only_when_smaller() {
        let line = "neutral status line with enough characters to reduce and some additional ordinary status detail";
        let original = vec![line; 6].join("\n");
        let result = compress_repeated_lines(&original, "12345678-1234-1234-1234-123456789abc");
        assert!(result.len() < original.len());
        assert!(result.contains("restore artifact"));
        assert_eq!(compress_repeated_lines("short\nshort\nshort", "x"), "short\nshort\nshort");
    }

    #[test]
    fn repeated_multiline_block_preserves_first_and_protected_text() {
        let a = "ordinary alpha status with enough detail to be useful and additional stable descriptive information";
        let b = "ordinary beta status with enough detail to be useful and additional stable descriptive information";
        let content = format!("{a}\n{b}\nseparator\n{a}\n{b}\nseparator\n{a}\n{b}");
        let result = compress_repeated_lines(&content, "12345678-1234-1234-1234-123456789abc");
        assert!(result.len() < content.len());
        assert!(result.starts_with(&format!("{a}\n{b}")));
        assert!(result.contains("original lines 1-2"));
        assert_eq!(result.matches("separator").count(), 2);
        let protected = "error on ordinary status line with enough detail";
        assert_eq!(compress_repeated_lines(&vec![protected; 4].join("\n"), "x"), vec![protected; 4].join("\n"));
    }
}
