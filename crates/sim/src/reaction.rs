//! Reactions: loading `content/reactions.json` (contract section 3) and compiling it to a dense
//! table over concrete material pairs (RXN-R02..R08, RXN-R17, RXN-R18).
//!
//! Semantics, all literal readings of the KB:
//! * outputs are positional: `out_a` replaces the cell that matched `a`, `out_b` the one that
//!   matched `b`;
//! * an output `[tag]` is "the material that matched that tag among the inputs";
//! * `@burning` matches any cell in the burning state, `@extinguish` keeps the material and clears
//!   the burning state;
//! * a pair is matched symmetrically (a visited cell may play either role);
//! * candidates of a pair are tried in file order, the first whose roll succeeds executes.

use crate::error::{Error, Result};
use crate::material::MaterialSet;
use serde::Deserialize;
use std::collections::BTreeSet;

pub const REACTIONS_FORMAT: &str = "cogbench-reactions/0";

/// One row as written in the content file; also the input of [`crate::Content::with_table`] (tests of other tables).
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct ReactionDef {
    pub id: String,
    pub a: String,
    pub b: String,
    pub out_a: String,
    pub out_b: String,
    /// Chance per examination, 0..=1.
    pub probability: f64,
    #[serde(default)]
    pub source: String,
}

#[derive(Deserialize)]
struct RawFile {
    format: String,
    reactions: Vec<ReactionDef>,
}

/// Parse `reactions.json` text. Semantic checks happen in [`ReactionTable::compile`].
pub fn parse_reactions_json(file: &str, text: &str) -> Result<Vec<ReactionDef>> {
    let raw: RawFile =
        serde_json::from_str(text).map_err(|e| Error::content(file, "(json)", e.to_string()))?;
    if raw.format != REACTIONS_FORMAT {
        return Err(Error::content(
            file,
            "format",
            format!("expected `{REACTIONS_FORMAT}`, found `{}`", raw.format),
        ));
    }
    Ok(raw.reactions)
}

/// What a reaction does to one of the two cells.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Out {
    /// Turn the cell into this material (a no-op if it already is).
    Set(u8),
    /// Keep the material, clear the burning state.
    Extinguish,
}

/// One concrete way a visited cell may react with a neighbour.
#[derive(Clone, Copy, Debug)]
pub struct Candidate {
    /// Index into [`ReactionTable::ids`].
    pub row: u16,
    /// Threshold of `below(10000)`.
    pub threshold: u16,
    pub visited_must_burn: bool,
    pub other_must_burn: bool,
    /// The visited cell plays role `a` of the row (otherwise role `b`).
    pub visited_is_a: bool,
    pub out_visited: Out,
    pub out_other: Out,
}

/// Compiled reaction table.
#[derive(Clone, Debug)]
pub struct ReactionTable {
    n: usize,
    cells: Vec<Vec<Candidate>>,
    ids: Vec<String>,
    reactive: Vec<bool>,
    /// `partners[a]` has bit `b` set if a cell of material `a` can react with a neighbour `b`
    /// under some condition: a cheap filter before the exact candidate check.
    partners: Vec<[u64; 4]>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Pattern {
    Material(u8),
    Tag(String),
    Burning,
}

impl Pattern {
    fn parse(file: &str, field: &str, s: &str, mats: &MaterialSet) -> Result<Pattern> {
        if s == "@burning" {
            return Ok(Pattern::Burning);
        }
        if let Some(tag) = s.strip_prefix('[').and_then(|r| r.strip_suffix(']')) {
            if mats.with_tag(tag).is_none() {
                return Err(Error::content(file, field, format!("unknown tag `{s}`")));
            }
            return Ok(Pattern::Tag(tag.to_string()));
        }
        match mats.index_of(s) {
            Some(i) => Ok(Pattern::Material(i)),
            None => Err(Error::content(
                file,
                field,
                format!("unknown material `{s}`"),
            )),
        }
    }

    /// Membership mask over material indices (air is never a member).
    fn mask(&self, mats: &MaterialSet) -> Vec<bool> {
        let mut mask = vec![false; mats.len()];
        match self {
            Pattern::Material(i) => mask[usize::from(*i)] = true,
            Pattern::Tag(t) => {
                for &i in mats.with_tag(t).unwrap_or(&[]) {
                    mask[usize::from(i)] = true;
                }
            }
            Pattern::Burning => mask.iter_mut().skip(1).for_each(|m| *m = true),
        }
        mask[0] = false;
        mask
    }
}

enum OutSpec {
    Material(u8),
    Tag(String),
    Extinguish,
}

fn parse_out(
    file: &str,
    field: &str,
    s: &str,
    mats: &MaterialSet,
    inputs: [&Pattern; 2],
    own: &Pattern,
) -> Result<OutSpec> {
    if s == "@extinguish" {
        if *own != Pattern::Burning {
            return Err(Error::content(
                file,
                field,
                "`@extinguish` is only valid in the slot whose input is `@burning`",
            ));
        }
        return Ok(OutSpec::Extinguish);
    }
    if let Some(tag) = s.strip_prefix('[').and_then(|r| r.strip_suffix(']')) {
        let wanted = Pattern::Tag(tag.to_string());
        if !inputs.contains(&&wanted) {
            return Err(Error::content(
                file,
                field,
                format!("output `{s}` has no matching `{s}` among the inputs"),
            ));
        }
        return Ok(OutSpec::Tag(tag.to_string()));
    }
    match mats.index_of(s) {
        Some(i) => Ok(OutSpec::Material(i)),
        None => Err(Error::content(
            file,
            field,
            format!("unknown material `{s}`"),
        )),
    }
}

struct ParsedRow {
    a: Pattern,
    b: Pattern,
    out_a: OutSpec,
    out_b: OutSpec,
    threshold: u16,
}

fn parse_row(file: &str, i: usize, r: &ReactionDef, mats: &MaterialSet) -> Result<ParsedRow> {
    let f = |name: &str| format!("reactions[{i}].{name} ({})", r.id);
    let a = Pattern::parse(file, &f("a"), &r.a, mats)?;
    let b = Pattern::parse(file, &f("b"), &r.b, mats)?;
    for (pat, name) in [(&a, "a"), (&b, "b")] {
        if matches!(pat, Pattern::Material(0)) {
            return Err(Error::content(
                file,
                f(name),
                "air cannot be a reaction input",
            ));
        }
    }
    if !(0.0..=1.0).contains(&r.probability) {
        return Err(Error::content(
            file,
            f("probability"),
            format!("must be in 0..=1, found {}", r.probability),
        ));
    }
    let out_a = parse_out(file, &f("out_a"), &r.out_a, mats, [&a, &b], &a)?;
    let out_b = parse_out(file, &f("out_b"), &r.out_b, mats, [&a, &b], &b)?;
    Ok(ParsedRow {
        a,
        b,
        out_a,
        out_b,
        threshold: (r.probability * 10_000.0).round() as u16,
    })
}

fn resolve(spec: &OutSpec, pa: &Pattern, pb: &Pattern, ma: u8, mb: u8) -> Out {
    match spec {
        OutSpec::Material(m) => Out::Set(*m),
        OutSpec::Extinguish => Out::Extinguish,
        OutSpec::Tag(t) => {
            let tag = Pattern::Tag(t.clone());
            if *pa == tag {
                Out::Set(ma)
            } else if *pb == tag {
                Out::Set(mb)
            } else {
                unreachable!("validated by parse_out")
            }
        }
    }
}

impl ReactionTable {
    /// An empty table (no reactions).
    pub fn empty(mats: &MaterialSet) -> ReactionTable {
        ReactionTable::compile("(none)", mats, &[]).expect("empty table always compiles")
    }

    /// Validate `defs` against `mats` and expand them over concrete material pairs.
    pub fn compile(file: &str, mats: &MaterialSet, defs: &[ReactionDef]) -> Result<ReactionTable> {
        let n = mats.len();
        let mut seen = BTreeSet::new();
        let mut table = ReactionTable {
            n,
            cells: vec![Vec::new(); n * n],
            ids: Vec::new(),
            reactive: vec![false; n],
            partners: vec![[0; 4]; n],
        };
        for (i, def) in defs.iter().enumerate() {
            if !seen.insert(def.id.clone()) {
                return Err(Error::content(
                    file,
                    format!("reactions[{i}].id"),
                    format!("duplicate id `{}`", def.id),
                ));
            }
            let row = parse_row(file, i, def, mats)?;
            let row_idx = table.ids.len() as u16;
            table.ids.push(def.id.clone());
            table.expand(mats, &row, row_idx);
        }
        for a in 0..n {
            for b in 0..n {
                if !table.cells[a * n + b].is_empty() {
                    table.partners[a][b / 64] |= 1 << (b % 64);
                    table.reactive[a] = true;
                }
            }
        }
        Ok(table)
    }

    fn expand(&mut self, mats: &MaterialSet, row: &ParsedRow, row_idx: u16) {
        let burn_a = row.a == Pattern::Burning;
        let burn_b = row.b == Pattern::Burning;
        let (in_a, in_b) = (row.a.mask(mats), row.b.mask(mats));
        for ma in (0..self.n).filter(|&m| in_a[m]) {
            for mb in (0..self.n).filter(|&m| in_b[m]) {
                // If the swapped pair matches too (and neither side is state-specific), the
                // orientation with the smaller index in role `a` wins, so the pair is not
                // registered twice.
                if burn_a == burn_b && ma > mb && in_a[mb] && in_b[ma] {
                    continue;
                }
                let (ia, ib) = (ma as u8, mb as u8);
                let out_a = resolve(&row.out_a, &row.a, &row.b, ia, ib);
                let out_b = resolve(&row.out_b, &row.a, &row.b, ia, ib);
                let base = Candidate {
                    row: row_idx,
                    threshold: row.threshold,
                    visited_must_burn: burn_a,
                    other_must_burn: burn_b,
                    visited_is_a: true,
                    out_visited: out_a,
                    out_other: out_b,
                };
                self.cells[ma * self.n + mb].push(base);
                // Same material on both sides: one orientation is enough unless the two slots
                // differ in whether they need a burning cell (then the swapped role is a
                // different situation, e.g. burning oil next to plain oil).
                if ma != mb || burn_a != burn_b {
                    let mirrored = Candidate {
                        visited_must_burn: burn_b,
                        other_must_burn: burn_a,
                        visited_is_a: false,
                        out_visited: out_b,
                        out_other: out_a,
                        ..base
                    };
                    self.cells[mb * self.n + ma].push(mirrored);
                }
            }
        }
    }

    /// Candidates for a visited cell of material `visited` next to a cell of material `other`,
    /// in file order.
    #[inline]
    pub fn candidates(&self, visited: u8, other: u8) -> &[Candidate] {
        let (v, o) = (usize::from(visited), usize::from(other));
        if v >= self.n || o >= self.n {
            return &[];
        }
        &self.cells[v * self.n + o]
    }

    /// Whether `visited` has any candidate against `other` (ignoring burning conditions).
    #[inline]
    pub fn may_react(&self, visited: u8, other: u8) -> bool {
        let (v, o) = (usize::from(visited), usize::from(other));
        v < self.n && o < self.n && (self.partners[v][o / 64] >> (o % 64)) & 1 == 1
    }

    /// Row ids in file order; `Candidate::row` indexes this.
    pub fn ids(&self) -> &[String] {
        &self.ids
    }

    /// Whether the material takes part in any reaction.
    pub fn is_reactive(&self, material: u8) -> bool {
        self.reactive
            .get(usize::from(material))
            .copied()
            .unwrap_or(false)
    }
}
