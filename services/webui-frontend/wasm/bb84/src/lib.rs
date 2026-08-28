//! BB84 Monte-Carlo inner loop, compiled to WebAssembly.
//!
//! WHY THIS EXISTS, AND WHAT WOULD MAKE IT NOT WORTH KEEPING
//!
//! `docs/roadmap.md` rejected WASM for this workload on bundle cost. That was a
//! reasonable prior and an untested one: nobody had built the module and
//! measured it. This crate turns the objection into a number. It is a fourth
//! tier in `bb84Sim.ts`, benchmarked against the CPU worker exactly as WebGPU
//! and WebGL2 are, and adopted only if it wins by the same 15 % margin.
//!
//! Deliberately `no_std`, no `wasm-bindgen`, no `rand`:
//!
//!   * `wasm-bindgen` would pull in a JS glue file and a heavier build step for
//!     a module whose entire interface is six numbers in and three out. Raw
//!     `WebAssembly.instantiate` needs neither.
//!   * `rand` would change the generator. The tiers have to be COMPARABLE, so
//!     this reproduces the worker's mulberry32 bit-for-bit -- see `rnd()`.
//!   * `no_std` + `opt-level="z"` + `lto` + `strip` keeps the artefact in the
//!     low kilobytes, which is the whole question the roadmap raised.
//!
//! The module owns no memory and allocates nothing: the caller passes the
//! parameters, the module returns sifted/errors/pulses packed into a single
//! u64 pair via two exported getters. No linear-memory marshalling, so there is
//! nothing to leak and nothing to keep in sync with a JS view.
#![no_std]

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    // `panic = "abort"` already prevents unwinding; this satisfies `no_std`.
    loop {}
}

/// mulberry32, byte-identical to `rnd()` in `bb84.worker.ts`.
///
/// The JS uses `Math.imul` and `>>> 0`, i.e. 32-bit wrapping multiply and a
/// logical shift. `wrapping_mul` on `u32` is the same operation; `>>` on `u32`
/// in Rust is already logical. Divided by 2^32 to land in [0, 1) exactly as the
/// worker does, so a given seed produces the same stream in both tiers.
#[inline(always)]
fn rnd(state: &mut u32) -> f64 {
    *state = state.wrapping_add(0x6d2b_79f5);
    let mut t = (*state ^ (*state >> 15)).wrapping_mul(1 | *state);
    t = (t.wrapping_add((t ^ (t >> 7)).wrapping_mul(61 | t))) ^ t;
    ((t ^ (t >> 14)) as f64) / 4_294_967_296.0
}

#[inline(always)]
fn bit(state: &mut u32) -> u8 {
    if rnd(state) < 0.5 { 0 } else { 1 }
}

/// One round. Returns `sifted` in the low 32 bits and `errors` in the high 32.
///
/// Mirrors `runRound()` in the worker statement for statement, including the
/// order of `rnd()` calls -- reordering them would still be a valid simulation
/// but would consume the stream differently and stop the two tiers agreeing on
/// a shared seed, which is how `wasmAgreesWithWorker` checks this port.
#[no_mangle]
pub extern "C" fn run_round(
    seed: u32,
    eta_total: f64,
    e_d: f64,
    y0: f64,
    eve_on: u32,
    eve_prob: f64,
    pulses: u32,
) -> u64 {
    let mut s = seed;
    let mut sifted: u32 = 0;
    let mut errors: u32 = 0;
    let detect = eta_total + y0;

    for _ in 0..pulses {
        if rnd(&mut s) >= detect {
            continue; // photon lost, or no dark count
        }
        let a_bit = bit(&mut s);
        let a_basis = bit(&mut s);
        let mut carried_bit = a_bit;
        let mut carried_basis = a_basis;

        if eve_on != 0 && rnd(&mut s) < eve_prob {
            let e_basis = bit(&mut s);
            let e_bit = if e_basis == a_basis { a_bit } else { bit(&mut s) };
            carried_bit = e_bit;
            carried_basis = e_basis;
        }

        let b_basis = bit(&mut s);
        let b_bit = if b_basis == carried_basis {
            if rnd(&mut s) < e_d { carried_bit ^ 1 } else { carried_bit }
        } else {
            bit(&mut s)
        };

        if a_basis == b_basis {
            sifted += 1;
            if a_bit != b_bit {
                errors += 1;
            }
        }
    }
    ((errors as u64) << 32) | (sifted as u64)
}
