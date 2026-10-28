//! Engine constants and the calibration knobs of the simulation.
//!
//! Material numbers (density, hp, fuel, ...) live in `content/materials.json`, never here.
//! What lives here are engine-level numbers the content files do not carry: chunk geometry,
//! wake margins and the [CAL] knobs of `pixel-simulation.md` (sink chance, mixing, gas speed).

/// Simulation chunk edge in cells (SIM-R02).
pub const CHUNK: i32 = 64;
/// Wake margin around a written cell (SIM-R11): the largest read distance of any rule.
pub const WAKE: i32 = 12;
/// Material index that stands for "outside the world" (SIM-R01). Never a real material.
pub const BOUNDARY: u8 = 255;
/// Largest world edge we accept, in cells.
pub const MAX_WORLD_EDGE: i32 = 8192;
/// Largest coordinate or size `paint` and `fill_rect` accept (keeps the arithmetic far from overflow).
pub const MAX_PAINT_EXTENT: i32 = 1 << 20;
/// Cap on fall steps per visit (SIM-R31).
pub const MAX_FALL_STEPS: u32 = 6;
/// Cap on the lateral hop of a liquid (SIM-R32).
pub const MAX_HOP: u8 = 10;
/// How far an ingredient cell looks through its own material for the other two ingredients of a
/// recipe (`rules/recipe_mix.rs`). Layers of liquid or powder up to this thick still mix across.
pub const MIX_REACH: i32 = 6;
const _: () = assert!(
    MIX_REACH <= WAKE,
    "a write must wake every cell that can see it"
);

/// Explosions that may run in one frame, and the sum of squared radii they may carry (SD12).
pub const MAX_EXPLOSIONS_PER_FRAME: usize = 32;
pub const MAX_EXPLOSION_R2_PER_FRAME: u64 = 400_000;
/// Largest explosion radius accepted by `explode`.
pub const MAX_EXPLOSION_RADIUS: u32 = 512;
/// Ray count of an explosion is at least this many (SIM-R51).
pub const MIN_EXPLOSION_RAYS: u32 = 16;

/// Defaults of `ConfigExplosion` (DUR-R03).
pub const DEFAULT_CREATE_FIRE_PERCENT: u8 = 5;

/// Contact damage (HAZ-R01): a material must touch at least this many cells of the entity's box
/// to hurt it, and counts for at most `CONTACT_MAX_CELLS` cells (a fully submerged player).
pub const CONTACT_MIN_CELLS: u32 = 4;
pub const CONTACT_MAX_CELLS: u32 = 85;

/// Longest move a box sweep follows, per axis, in cells. Longer moves are cut to this.
pub const MAX_SWEEP: i32 = 1 << 14;

/// At most this many events are buffered between two `events()` calls.
pub const MAX_BUFFERED_EVENTS: usize = 250_000;

/// Calibration knobs (all `[CAL]` in `pixel-simulation.md`). Probabilities are `x/256`;
/// 256 means "always". `Tuning::forced()` is the deterministic test configuration `T`
/// of the KB test vectors.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Tuning {
    /// A liquid sinks into a lighter liquid below it with this chance (SIM-R30).
    pub sink_liquid_q8: u16,
    /// A powder sinks into a lighter liquid with this chance.
    pub sink_powder_q8: u16,
    /// Two equal-density liquids swap sideways with this chance (SIM-R33).
    pub mix_q8: u16,
    /// A hopping liquid flips its preferred direction with this chance (SIM-R32).
    pub dir_flip_q8: u16,
    /// A gas or fire cell acts in a frame with this chance (SIM-R34).
    pub gas_act_q8: u16,
    /// Lateral hop range of liquids, in cells (`flow / (1 - damping)` with Noita defaults: 5).
    pub liquid_hop: u8,
    /// Initial timer jitter in percent (SIM-R35).
    pub life_jitter_pct: u8,
    /// Chance per frame that a burning cell emits a flame (`generates_flames` default 30).
    pub flame_percent: u8,
    /// Fire cells live a uniform number of frames in this range (SD for FIRE-R07, D6).
    pub fire_life_min: u8,
    pub fire_life_max: u8,
    /// Chance per visit that an ingredient cell that sees the other two ingredients of a recipe
    /// turns the three into the potion (`rules/recipe_mix.rs`).
    pub recipe_mix_q8: u16,
    /// Test configuration: every faller moves exactly one cell per visit.
    pub single_fall_step: bool,
}

impl Default for Tuning {
    fn default() -> Self {
        Tuning {
            sink_liquid_q8: 192,
            sink_powder_q8: 256,
            mix_q8: 16,
            dir_flip_q8: 32,
            gas_act_q8: 128,
            liquid_hop: 5,
            life_jitter_pct: 12,
            flame_percent: 30,
            fire_life_min: 12,
            fire_life_max: 30,
            recipe_mix_q8: 64,
            single_fall_step: false,
        }
    }
}

impl Tuning {
    /// Test configuration `T` of `pixel-simulation.md`: no randomness in motion.
    pub fn forced() -> Self {
        Tuning {
            sink_liquid_q8: 256,
            sink_powder_q8: 256,
            mix_q8: 0,
            dir_flip_q8: 0,
            gas_act_q8: 256,
            life_jitter_pct: 0,
            fire_life_min: 20,
            fire_life_max: 20,
            recipe_mix_q8: 256,
            single_fall_step: true,
            ..Tuning::default()
        }
    }
}
