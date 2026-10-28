//! Deterministic trigonometry for explosion rays (DET-R06): only `+ - * /` and `floor`,
//! which are exactly rounded IEEE operations, so every platform gets the same bits.

use std::f64::consts::{FRAC_PI_2, TAU};

/// `(sin x, cos x)` for any finite `x`, computed with range reduction and Taylor series.
pub fn sin_cos(x: f64) -> (f64, f64) {
    let turns = (x / TAU).floor();
    let x = x - turns * TAU; // [0, 2π)
    let quadrant = (x / FRAC_PI_2).floor();
    let r = x - quadrant * FRAC_PI_2; // [0, π/2)
    let (s, c) = taylor(r);
    match (quadrant as i64).rem_euclid(4) {
        0 => (s, c),
        1 => (c, -s),
        2 => (-s, -c),
        _ => (-c, s),
    }
}

fn taylor(r: f64) -> (f64, f64) {
    let r2 = r * r;
    let mut sin = r;
    let mut cos = 1.0;
    let mut term_s = r;
    let mut term_c = 1.0;
    for k in 1..=12 {
        let kf = k as f64;
        term_c = -term_c * r2 / ((2.0 * kf - 1.0) * (2.0 * kf));
        term_s = -term_s * r2 / ((2.0 * kf) * (2.0 * kf + 1.0));
        cos += term_c;
        sin += term_s;
    }
    (sin, cos)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_std_closely() {
        for i in 0..2000 {
            let x = i as f64 * 0.0123 - 3.0;
            let (s, c) = sin_cos(x);
            assert!((s - x.sin()).abs() < 1e-12, "sin({x})");
            assert!((c - x.cos()).abs() < 1e-12, "cos({x})");
        }
    }
}
