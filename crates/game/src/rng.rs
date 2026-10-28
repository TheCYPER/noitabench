//! Randomness of the spell system (DET-R04, SPELL-R43).
//!
//! Spells never see the wall clock or the frame number: card shuffling and the spread angle come
//! from the `spells` stream of the episode seed. The hash functions are the same SplitMix64 ones as
//! `cogbench_sim::rng`, so a stream seed derived here equals the one derived there; they are
//! repeated (a dozen lines) because this crate does not depend on the simulation crate yet.
//!
//! Shuffling and spread use two independent sub-streams, so changing a wand's spread cannot change
//! the order a shuffle wand deals its cards in.

use serde::{Deserialize, Serialize};

const GAMMA: u64 = 0x9E37_79B9_7F4A_7C15;

/// SplitMix64 finaliser: a bijective, well-mixing 64-bit hash.
pub fn mix64(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h = 0xcbf2_9ce4_8422_2325u64;
    for b in bytes {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

/// Seed of the named stream `name` of an episode seed (same formula as `cogbench_sim::rng`).
pub fn stream_seed(seed: u64, name: &str) -> u64 {
    mix64(seed ^ mix64(fnv1a(name.as_bytes())))
}

/// What the casting code needs from a random source.
pub trait SpellRandom {
    /// Uniform integer in `0..n` for dealing a shuffled deck; `n >= 1`.
    fn shuffle_index(&mut self, n: u32) -> u32;
    /// Uniform `f32` in `[0, 1)` for the spread angle of one projectile.
    fn spread_unit(&mut self) -> f32;
}

fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_add(GAMMA);
    mix64(*state)
}

/// The production source: two SplitMix64 sub-streams of the `spells` stream.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SpellRng {
    shuffle: u64,
    spread: u64,
}

impl SpellRng {
    /// Streams for the episode `seed`.
    pub fn new(seed: u64) -> Self {
        let spells = stream_seed(seed, "spells");
        SpellRng {
            shuffle: stream_seed(spells, "shuffle"),
            spread: stream_seed(spells, "spread"),
        }
    }
}

impl SpellRandom for SpellRng {
    fn shuffle_index(&mut self, n: u32) -> u32 {
        debug_assert!(n >= 1);
        // Multiply-high maps a 64-bit draw onto 0..n with a bias below 2^-32 for n <= 2^32.
        ((u128::from(next(&mut self.shuffle)) * u128::from(n)) >> 64) as u32
    }

    fn spread_unit(&mut self) -> f32 {
        // 24 random bits are exactly representable in an f32.
        (next(&mut self.spread) >> 40) as f32 / 16_777_216.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_seed_same_stream() {
        let mut a = SpellRng::new(7);
        let mut b = SpellRng::new(7);
        for _ in 0..100 {
            assert_eq!(a.shuffle_index(26), b.shuffle_index(26));
            assert_eq!(a.spread_unit().to_bits(), b.spread_unit().to_bits());
        }
        assert_ne!(SpellRng::new(7), SpellRng::new(8));
    }

    #[test]
    fn sub_streams_are_independent() {
        let mut a = SpellRng::new(3);
        let mut b = SpellRng::new(3);
        for _ in 0..10 {
            a.spread_unit();
        }
        assert_eq!(a.shuffle_index(1000), b.shuffle_index(1000));
    }

    #[test]
    fn draws_stay_in_range() {
        let mut rng = SpellRng::new(1);
        for n in 1..200 {
            assert!(rng.shuffle_index(n) < n);
            let u = rng.spread_unit();
            assert!((0.0..1.0).contains(&u));
        }
    }

    #[test]
    fn shuffle_index_is_uniform() {
        // 10,000 draws over 5 buckets: each bucket within 4 sigma of 2,000 (sigma = 40).
        let mut rng = SpellRng::new(99);
        let mut counts = [0u32; 5];
        for _ in 0..10_000 {
            counts[rng.shuffle_index(5) as usize] += 1;
        }
        for c in counts {
            assert!((1840..=2160).contains(&c), "bucket count {c}");
        }
    }
}

/// Stateless random numbers for everything in the game layer except card dealing: a hash of the
/// stream seed, the frame, an entity id and a salt. Nothing is stored between draws, so there is
/// no generator state to snapshot, and one entity's draws never shift another's (DET-R04).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HashRng {
    seed: u64,
}

impl HashRng {
    /// The named stream (`"ai"`, `"spawn"`, ...) of an episode seed.
    pub fn stream(seed: u64, name: &str) -> HashRng {
        HashRng {
            seed: stream_seed(seed, name),
        }
    }

    /// 64 random bits for `(a, b, c)`.
    pub fn bits(&self, a: u64, b: u64, c: u64) -> u64 {
        let h = mix64(self.seed ^ a.wrapping_mul(GAMMA));
        let h = mix64(h ^ b.wrapping_mul(0xD6E8_FEB8_6659_FD93));
        mix64(h ^ c.wrapping_mul(0xA076_1D64_78BD_642F))
    }

    /// Uniform integer in `0..n` (`n >= 1`).
    pub fn below(&self, n: u32, a: u64, b: u64, c: u64) -> u32 {
        debug_assert!(n >= 1);
        (((self.bits(a, b, c) >> 32) * u64::from(n)) >> 32) as u32
    }

    /// Uniform `f32` in `[0, 1)`.
    pub fn unit(&self, a: u64, b: u64, c: u64) -> f32 {
        (self.bits(a, b, c) >> 40) as f32 / 16_777_216.0
    }

    /// `true` with probability `percent / 100`.
    pub fn percent(&self, percent: u32, a: u64, b: u64, c: u64) -> bool {
        percent >= 100 || (percent > 0 && self.below(100, a, b, c) < percent)
    }

    /// Uniform integer in `lo..=hi`.
    pub fn range(&self, lo: i64, hi: i64, a: u64, b: u64, c: u64) -> i64 {
        debug_assert!(lo <= hi);
        lo + i64::from(self.below((hi - lo + 1) as u32, a, b, c))
    }
}

#[cfg(test)]
mod hash_rng_tests {
    use super::*;

    #[test]
    fn hash_rng_is_stateless_and_stream_separated() {
        let a = HashRng::stream(5, "ai");
        let b = HashRng::stream(5, "spawn");
        assert_eq!(a.bits(1, 2, 3), a.bits(1, 2, 3));
        assert_ne!(a.bits(1, 2, 3), b.bits(1, 2, 3));
        assert_ne!(a.bits(1, 2, 3), a.bits(1, 2, 4));
        let mut buckets = [0u32; 4];
        for i in 0..8_000u64 {
            buckets[a.below(4, i, 0, 0) as usize] += 1;
        }
        for n in buckets {
            assert!((1_800..2_200).contains(&n), "{buckets:?}");
        }
        assert!((0..100).all(|i| (0.0..1.0).contains(&a.unit(i, 0, 0))));
        assert_eq!(a.range(3, 3, 9, 9, 9), 3);
    }
}
