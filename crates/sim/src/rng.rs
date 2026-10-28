//! Randomness (SIM-R70, DET-R04).
//!
//! Cell randomness is a *stateless* hash of `(seed, frame, pass, cell index)`: there is no shared
//! mutable generator, so neither visit order nor dirty rectangles can leak into the stream a cell
//! sees. Everything else (world generation, spawns, ...) uses named streams derived from the
//! seed.

const K1: u64 = 0x9E37_79B9_7F4A_7C15;
const K3: u64 = 0x1656_67B1_9E37_79F9;
const K4: u64 = 0xD6E8_FEB8_6659_FD93;

/// SplitMix64 finaliser: a bijective, well-mixing 64-bit hash.
#[inline]
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

/// Seed of the named stream `name` (`"worldgen"`, `"cells"`, `"spells"`, `"ai"`, `"spawn"`, ...).
pub fn stream_seed(seed: u64, name: &str) -> u64 {
    mix64(seed ^ mix64(fnv1a(name.as_bytes())))
}

/// Per-frame key: computed once per frame, then combined with `(pass, index)` per visit.
#[inline]
pub fn frame_key(cell_seed: u64, frame: u64) -> u64 {
    mix64(cell_seed ^ frame.wrapping_mul(K1))
}

/// Hash of one `(frame, pass, index)` triple. Unrelated draws that would share a triple (cell
/// creation, the slow-liquid frame gate, explosions) use distinct `pass` values above 3.
#[inline]
pub fn hash_at(frame_key: u64, pass: u8, index: u32) -> u64 {
    let x = (u64::from(pass) << 32) | u64::from(index);
    mix64(frame_key ^ x.wrapping_mul(K3))
}

/// Random draws of one cell visit. The 64-bit hash is derived lazily on the first draw (most
/// visits draw nothing) and consumed byte-wise; after eight bytes it is re-hashed with a counter.
#[derive(Clone, Debug)]
pub struct CellRng {
    frame_key: u64,
    pass: u8,
    index: u32,
    base: u64,
    counter: u64,
    buf: u64,
    avail: u8,
}

impl CellRng {
    #[inline]
    pub fn new(frame_key: u64, pass: u8, index: u32) -> Self {
        CellRng {
            frame_key,
            pass,
            index,
            base: 0,
            counter: 0,
            buf: 0,
            avail: 0,
        }
    }

    #[inline]
    fn refill(&mut self) {
        if self.counter == 0 {
            self.base = hash_at(self.frame_key, self.pass, self.index);
            self.buf = self.base;
        } else {
            self.buf = mix64(self.base ^ self.counter.wrapping_mul(K4));
        }
        self.counter += 1;
        self.avail = 8;
    }

    #[inline]
    pub fn byte(&mut self) -> u8 {
        if self.avail == 0 {
            self.refill();
        }
        let v = self.buf as u8;
        self.buf >>= 8;
        self.avail -= 1;
        v
    }

    #[inline]
    pub fn next_u32(&mut self) -> u32 {
        if self.avail < 4 {
            self.refill();
        }
        let v = self.buf as u32;
        self.buf >>= 32;
        self.avail -= 4;
        v
    }

    /// `true` with probability `p / 256`; `p >= 256` is certain and draws nothing.
    #[inline]
    pub fn chance_q8(&mut self, p: u16) -> bool {
        if p >= 256 {
            return true;
        }
        if p == 0 {
            return false;
        }
        u16::from(self.byte()) < p
    }

    /// Uniform integer in `0..n` (multiply-shift, bias below 2^-16 for `n <= 2^16`).
    #[inline]
    pub fn below(&mut self, n: u32) -> u32 {
        debug_assert!(n > 0);
        ((u64::from(self.next_u32()) * u64::from(n)) >> 32) as u32
    }

    #[inline]
    pub fn bit(&mut self) -> bool {
        self.byte() & 1 == 1
    }
}

/// A named sequential stream for code that is not a cell rule (SplitMix64).
#[derive(Clone, Debug)]
pub struct Stream {
    state: u64,
}

impl Stream {
    pub fn new(seed: u64, name: &str) -> Self {
        Stream {
            state: stream_seed(seed, name),
        }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(K1);
        mix64(self.state)
    }

    pub fn below(&mut self, n: u32) -> u32 {
        debug_assert!(n > 0);
        (((self.next_u64() >> 32) * u64::from(n)) >> 32) as u32
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mix64_is_stable() {
        // Golden values: changing the hash changes every simulation (VER-R02).
        assert_eq!(mix64(0), 0);
        assert_eq!(mix64(1), 0x5692_161d_100b_05e5);
    }

    #[test]
    fn same_triple_same_stream_different_triple_differs() {
        let fk = frame_key(7, 12);
        let mut a = CellRng::new(fk, 1, 99);
        let mut b = CellRng::new(fk, 1, 99);
        let mut c = CellRng::new(fk, 2, 99);
        let va: Vec<u32> = (0..6).map(|_| a.next_u32()).collect();
        let vb: Vec<u32> = (0..6).map(|_| b.next_u32()).collect();
        let vc: Vec<u32> = (0..6).map(|_| c.next_u32()).collect();
        assert_eq!(va, vb);
        assert_ne!(va, vc);
    }

    #[test]
    fn det_r04_named_streams_are_independent() {
        let names = ["worldgen", "cells", "spells", "ai", "spawn"];
        let seeds: Vec<u64> = names.iter().map(|n| stream_seed(99, n)).collect();
        for (i, a) in seeds.iter().enumerate() {
            for b in &seeds[i + 1..] {
                assert_ne!(a, b);
            }
        }
        assert_ne!(stream_seed(1, "cells"), stream_seed(2, "cells"));
        let (mut a, mut b) = (Stream::new(5, "ai"), Stream::new(5, "ai"));
        assert_eq!(a.next_u64(), b.next_u64());
        assert_ne!(a.next_u64(), Stream::new(5, "spawn").next_u64());
    }

    #[test]
    fn below_is_roughly_uniform() {
        let fk = frame_key(1, 1);
        let mut buckets = [0u32; 4];
        for i in 0..40_000u32 {
            let mut r = CellRng::new(fk, 0, i);
            buckets[r.below(4) as usize] += 1;
        }
        for b in buckets {
            assert!((9_500..10_500).contains(&b), "{buckets:?}");
        }
    }
}
