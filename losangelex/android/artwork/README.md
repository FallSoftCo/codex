# Hollywood Hills launcher icon

The color artwork shows the white Hollywood sign above teal hills, using the app's existing
mint and dark background palette. The themed version reduces it to block lettering and two
hill contours. Both assets were generated with the built-in image-generation tool; the selected
PNG files retain their original alpha and pixels in `app/src/main/res/drawable-nodpi/`.

- [Color artwork](../app/src/main/res/drawable-nodpi/hollywood_hills.png), [exact prompt](color-prompt.txt).
- [Monochrome alpha mask](../app/src/main/res/drawable-nodpi/hollywood_hills_monochrome.png), [exact prompt](monochrome-prompt.txt).
- [Browser preview](preview.html) and [captured preview](preview.png), including a small launcher-size example.

The manifest references adaptive `ic_launcher` resources. Android 13 and newer receive the
explicit monochrome layer. The drawable insets keep the prominent sign inside the mask-safe
region while the system supplies the outer icon shape. These are browser artwork previews;
they are not Android device screenshots. See [Android's adaptive-icon guidance](https://developer.android.com/develop/ui/compose/system/icon_design_adaptive).

Version 0.1.1 passed the release build and Android lint, was signed with the existing release
certificate, and was installed over 0.1.0 on the Pixel 9 Pro Fold. The installed APK and private
download match the release SHA-256. The app retained its connection and notification registration,
and the host room process did not restart. See the [release receipt](release.json) and
[actual Android App info screenshot](pixel-app-info.png), reviewed after installation.

The earlier notification and room behavior runs remain evidence for 0.1.0. This artwork update
changes launcher resources, manifest icon references, and the app version; those behavior suites
were not repeated.
