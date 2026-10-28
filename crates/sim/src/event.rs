//! The event log: facts about the simulation, deterministic and part of reproducibility.

use crate::content::Content;

/// One logged fact. Positions are cell coordinates.
#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    /// Reaction row `row` fired; `(x, y)` is the cell that played role `a`, `(bx, by)` role `b`.
    Reaction {
        frame: u64,
        row: u16,
        x: i32,
        y: i32,
        bx: i32,
        by: i32,
    },
    /// A burnable cell caught fire from a cell of material `by`.
    Ignite {
        frame: u64,
        x: i32,
        y: i32,
        material: u8,
        by: u8,
    },
    /// A burning cell was put out by a reaction.
    Extinguish {
        frame: u64,
        x: i32,
        y: i32,
        material: u8,
    },
    /// A ray explosion carved `destroyed` cells.
    Explosion {
        frame: u64,
        x: i32,
        y: i32,
        radius: u32,
        destroyed: u32,
    },
    /// The in-memory event buffer was full and `dropped` events were not kept (they are still in
    /// a recording, if one is running).
    Overflow { frame: u64, dropped: u64 },
    /// A fact of the game layer (damage, death, pickup, ...): `kind` is the `type` of the JSON
    /// line and `fields` follow `frame` and `type` in order (`World::log_event`).
    Game {
        frame: u64,
        kind: &'static str,
        fields: Vec<(&'static str, Value)>,
    },
}

/// A scalar field of an event, for JSON lines and Python dicts.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Int(i64),
    /// Finite numbers only (`NaN` and infinities are written as `0.0`).
    Float(f64),
    Str(String),
}

impl Event {
    pub fn frame(&self) -> u64 {
        match self {
            Event::Reaction { frame, .. }
            | Event::Ignite { frame, .. }
            | Event::Extinguish { frame, .. }
            | Event::Explosion { frame, .. }
            | Event::Overflow { frame, .. }
            | Event::Game { frame, .. } => *frame,
        }
    }

    /// Fields in a fixed order, starting with `frame` and `type`.
    pub fn fields(&self, c: &Content) -> Vec<(&'static str, Value)> {
        use Value::{Int, Str};
        let head = |kind: &str| {
            vec![
                ("frame", Int(self.frame() as i64)),
                ("type", Str(kind.to_string())),
            ]
        };
        let key = |m: u8| Str(c.mats.key_of(m).to_string());
        match self {
            Event::Reaction {
                row, x, y, bx, by, ..
            } => {
                let mut v = head("reaction");
                v.push(("id", Str(c.table.ids()[usize::from(*row)].clone())));
                v.extend([
                    ("x", Int(i64::from(*x))),
                    ("y", Int(i64::from(*y))),
                    ("bx", Int(i64::from(*bx))),
                    ("by", Int(i64::from(*by))),
                ]);
                v
            }
            Event::Ignite {
                x, y, material, by, ..
            } => {
                let mut v = head("ignite");
                v.extend([
                    ("x", Int(i64::from(*x))),
                    ("y", Int(i64::from(*y))),
                    ("material", key(*material)),
                    ("by", key(*by)),
                ]);
                v
            }
            Event::Extinguish { x, y, material, .. } => {
                let mut v = head("extinguish");
                v.extend([
                    ("x", Int(i64::from(*x))),
                    ("y", Int(i64::from(*y))),
                    ("material", key(*material)),
                ]);
                v
            }
            Event::Explosion {
                x,
                y,
                radius,
                destroyed,
                ..
            } => {
                let mut v = head("explosion");
                v.extend([
                    ("x", Int(i64::from(*x))),
                    ("y", Int(i64::from(*y))),
                    ("radius", Int(i64::from(*radius))),
                    ("destroyed", Int(i64::from(*destroyed))),
                ]);
                v
            }
            Event::Overflow { dropped, .. } => {
                let mut v = head("overflow");
                v.push(("dropped", Int(*dropped as i64)));
                v
            }
            Event::Game { kind, fields, .. } => {
                let mut v = head(kind);
                v.extend(fields.iter().cloned());
                v
            }
        }
    }

    /// One `events.jsonl` line (without the trailing newline).
    pub fn to_json_line(&self, c: &Content) -> String {
        let mut out = String::from("{");
        for (i, (name, value)) in self.fields(c).into_iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            out.push('"');
            out.push_str(name);
            out.push_str("\":");
            match value {
                Value::Int(n) => out.push_str(&n.to_string()),
                // `{:?}` keeps a `.0` on whole numbers, so a float stays a float when read back.
                Value::Float(f) if f.is_finite() => out.push_str(&format!("{f:?}")),
                Value::Float(_) => out.push_str("0.0"),
                // serde_json escapes quotes and control characters correctly.
                Value::Str(s) => out.push_str(&serde_json::to_string(&s).unwrap_or_default()),
            }
        }
        out.push('}');
        out
    }
}
