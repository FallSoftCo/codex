//! Local cost estimates for models whose rates Codex does not price itself.
//!
//! Codex only knows the rates of the models it bills for, so a session running
//! against a custom `model_provider` has no cost surface at all. When the user
//! supplies `[model_prices]` in `config.toml`, these helpers turn the session's
//! token usage into a local estimate.
//!
//! The result is a user-supplied estimate, never a billed amount; callers must
//! keep it distinguishable from authoritative billing data.

use crate::token_usage::TokenUsage;
use codex_config::types::ModelPrice;

/// Estimated cost of `usage` under `price`, in micro-dollars (1e-6 USD).
pub(crate) fn cost_micros(usage: &TokenUsage, price: &ModelPrice) -> u64 {
    let cached = usage.cached_input().max(0) as f64;
    let uncached = usage.non_cached_input().max(0) as f64;
    let output = usage.output_tokens.max(0) as f64;

    let dollars = (cached * price.input_cached_per_million
        + uncached * price.input_uncached_per_million
        + output * price.output_per_million)
        / 1_000_000.0;
    if !dollars.is_finite() || dollars <= 0.0 {
        return 0;
    }
    (dollars * 1_000_000.0).round() as u64
}

/// Formats micro-dollars for a status surface, e.g. `$0.18` or `$0.0002`.
pub(crate) fn format_cost_micros(micros: u64) -> String {
    let dollars = micros as f64 / 1_000_000.0;
    if micros < 10_000 {
        format!("${dollars:.4}")
    } else if micros < 1_000_000 {
        format!("${dollars:.3}")
    } else {
        format!("${dollars:.2}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn price(input_cached: f64, input_uncached: f64, output: f64) -> ModelPrice {
        ModelPrice {
            input_cached_per_million: input_cached,
            input_uncached_per_million: input_uncached,
            output_per_million: output,
        }
    }

    fn usage(input: i64, cached: i64, output: i64) -> TokenUsage {
        TokenUsage {
            input_tokens: input,
            cached_input_tokens: cached,
            output_tokens: output,
            reasoning_output_tokens: 0,
            total_tokens: input + output,
        }
    }

    #[test]
    fn splits_cached_and_uncached_input() {
        let rate = price(
            /*input_cached*/ 0.006, /*input_uncached*/ 0.30, /*output*/ 1.20,
        );
        // 1M cached + 1M uncached + 1M output = 0.006 + 0.30 + 1.20 USD.
        let cost = cost_micros(&usage(2_000_000, 1_000_000, 1_000_000), &rate);
        assert_eq!(cost, 1_506_000);
    }

    #[test]
    fn charges_only_the_uncached_remainder_at_the_uncached_rate() {
        let rate = price(
            /*input_cached*/ 0.0, /*input_uncached*/ 1.0, /*output*/ 0.0,
        );
        let cost = cost_micros(&usage(4_000_000, 3_000_000, 0), &rate);
        assert_eq!(cost, 1_000_000);
    }

    #[test]
    fn clamps_negative_usage_to_zero() {
        let rate = price(1.0, 1.0, 1.0);
        assert_eq!(cost_micros(&usage(-5, -5, -5), &rate), 0);
    }

    #[test]
    fn formats_by_magnitude() {
        assert_eq!(format_cost_micros(180_000), "$0.180");
        assert_eq!(format_cost_micros(200), "$0.0002");
        assert_eq!(format_cost_micros(2_500_000), "$2.50");
    }
}
