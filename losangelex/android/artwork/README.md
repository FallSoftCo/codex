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

The first two monochrome edits were rejected because they lost letter separation; the selected
mask was generated separately with broad negative space. No rejected variants are packaged.
