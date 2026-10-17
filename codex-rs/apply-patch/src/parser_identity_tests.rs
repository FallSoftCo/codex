use crate::parse_patch;
use crate::parse_patch_streaming;
use pretty_assertions::assert_eq;

#[test]
fn ordinary_and_streaming_parsers_preserve_the_same_consented_patch_argument() {
    let patch = "*** Begin Patch\n*** Add File: readiness.py\n+print('ready')\n*** End Patch";
    for argument in [patch.to_string(), format!("{patch}\n")] {
        let parsed = parse_patch(&argument).expect("ordinary patch parses");
        let streamed = parse_patch_streaming(&argument).expect("streaming patch parses");
        assert_eq!(parsed.patch.as_bytes(), argument.as_bytes());
        assert_eq!(parsed, streamed);
    }
}
