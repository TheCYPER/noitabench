//! Python bindings for the simulation and the game: the module `noitabench_core`.
//!
//! Wrappers only: every rule lives in `cogbench-sim` and `cogbench-game`.

mod common;
mod convert;
mod env;
mod game;
mod queries;
mod rules;
mod trial;

use env::Env;
use game::Game;
use pyo3::prelude::*;
use rules::Rules;

/// The simulation core of the cogbench environment (Rust).
#[pymodule]
mod noitabench_core {
    #[pymodule_export]
    use super::rules::recipes;
    #[pymodule_export]
    use super::rules::rules;
    #[pymodule_export]
    use super::trial::wand_trial;
    #[pymodule_export]
    use super::Env;
    #[pymodule_export]
    use super::Game;
    #[pymodule_export]
    use super::Rules;

    use pyo3::prelude::*;

    #[pymodule_init]
    fn init(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add("__version__", env!("CARGO_PKG_VERSION"))?;
        m.add("RECORDING_FORMAT", cogbench_sim::record::RECORDING_FORMAT)?;
        Ok(())
    }
}
