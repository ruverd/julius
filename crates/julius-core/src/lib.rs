use std::collections::HashMap;

/// Replace only repeated, exact, neutral lines; an external artifact retains the original.
pub fn compress_repeated_lines(content: &str, artifact_id: &str) -> String {
    let lines: Vec<&str> = content.split('\n').collect();
    let neutral = |line: &str| {
        line.len() >= 16 && line.chars().all(|c| c.is_ascii_alphanumeric() || " _.,:;/()-".contains(c))
    };
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
}
