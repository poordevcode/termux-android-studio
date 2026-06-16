#!/usr/bin/env python3
"""
studio_new.py - scaffold a new Android project that builds with the Termux toolchain.

Usage: studio_new.py --name NAME --template {compose|xml} --dir PARENT_DIR [--package PKG]

Mirrors the proven version set on this device (AGP 9.2.1 / Gradle 9.5 / compileSdk 37,
AGP built-in Kotlin) and the same default file layout Android Studio's "Empty Activity"
templates produce — for Compose: ui/theme/{Color,Theme,Type}.kt + a <Name>Theme; for Views:
colors.xml + Material3 themes (light + night) + a ViewBinding activity.
"""
import argparse
import os
import re
import shutil
import sys

WRAPPER_SRC = "/storage/emulated/0/AndroidIDEProjects/FCMClient"  # reuse a known-good wrapper
GRADLE_VERSION = "9.5"
AGP_VERSION = "9.2.1"
COMPOSE_PLUGIN_VERSION = "2.3.10"

C = {
    "g": "\033[92m", "y": "\033[93m", "r": "\033[91m",
    "c": "\033[96m", "b": "\033[1m", "e": "\033[0m",
}


def die(msg):
    print(f"{C['r']}error:{C['e']} {msg}", file=sys.stderr)
    sys.exit(1)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def sanitize_pkg_segment(s):
    s = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    if not s:
        s = "app"
    if s[0].isdigit():
        s = "a" + s
    return s


def pascal_case(name):
    """'My App' -> 'MyApp' — used for the theme name, like Android Studio."""
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    pc = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not pc:
        pc = "App"
    if pc[0].isdigit():
        pc = "App" + pc
    return pc


# ---------------------------------------------------------------- shared files

def f_gitignore():
    return (
        "*.iml\n.gradle\n/local.properties\n/.idea\n.DS_Store\n/build\n"
        "/captures\n.externalNativeBuild\n.cxx\nlocal.properties\n.studio/\n"
    )


def f_gradle_properties():
    return (
        "org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\n"
        "android.useAndroidX=true\n"
        "android.nonTransitiveRClass=true\n"
        "kotlin.code.style=official\n"
    )


def f_settings(name, compose):
    plugins = ""
    if compose:
        plugins = (
            "    plugins {\n"
            f'        id("org.jetbrains.kotlin.plugin.compose") version "{COMPOSE_PLUGIN_VERSION}"\n'
            "    }\n"
        )
    return (
        "pluginManagement {\n"
        f"{plugins}"
        "    repositories {\n"
        "        google {\n"
        "            content {\n"
        '                includeGroupByRegex("com\\\\.android.*")\n'
        '                includeGroupByRegex("com\\\\.google.*")\n'
        '                includeGroupByRegex("androidx.*")\n'
        "            }\n"
        "        }\n"
        "        mavenCentral()\n"
        "        gradlePluginPortal()\n"
        "    }\n"
        "}\n"
        "dependencyResolutionManagement {\n"
        "    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)\n"
        "    repositories {\n"
        "        google()\n"
        "        mavenCentral()\n"
        "    }\n"
        "}\n"
        f'rootProject.name = "{name}"\n'
        "include ':app'\n"
    )


def f_root_build(compose):
    if compose:
        return (
            "plugins {\n"
            f"    id 'com.android.application' version '{AGP_VERSION}' apply false\n"
            "    id 'org.jetbrains.kotlin.plugin.compose' apply false\n"
            "}\n"
        )
    return (
        "plugins {\n"
        f"    id 'com.android.application' version '{AGP_VERSION}' apply false\n"
        "}\n"
    )


def f_app_build(pkg, compose):
    head = "import org.jetbrains.kotlin.gradle.dsl.JvmTarget\n\n"
    if compose:
        plugins = (
            "plugins {\n"
            "    id 'com.android.application'\n"
            "    id 'org.jetbrains.kotlin.plugin.compose'\n"
            "}\n"
        )
        features = "    buildFeatures {\n        compose = true\n    }\n"
        deps = (
            "    implementation 'androidx.core:core-ktx:1.19.0'\n"
            "    implementation 'androidx.lifecycle:lifecycle-runtime-ktx:2.10.0'\n"
            "    implementation 'androidx.activity:activity-compose:1.13.0'\n"
            '    implementation(platform("androidx.compose:compose-bom:2026.05.01"))\n'
            "    implementation 'androidx.compose.ui:ui'\n"
            "    implementation 'androidx.compose.ui:ui-graphics'\n"
            "    implementation 'androidx.compose.ui:ui-tooling-preview'\n"
            "    implementation 'androidx.compose.material3:material3'\n"
            "    debugImplementation 'androidx.compose.ui:ui-tooling'\n"
        )
    else:
        plugins = (
            "plugins {\n"
            "    id 'com.android.application'\n"
            "}\n"
        )
        features = "    buildFeatures {\n        viewBinding true\n    }\n"
        deps = (
            "    implementation 'androidx.core:core-ktx:1.19.0'\n"
            "    implementation 'androidx.appcompat:appcompat:1.7.0'\n"
            "    implementation 'com.google.android.material:material:1.12.0'\n"
            "    implementation 'androidx.constraintlayout:constraintlayout:2.2.0'\n"
        )
    return (
        head + plugins +
        "\nandroid {\n"
        f"    namespace = '{pkg}'\n"
        "    compileSdk 37\n"
        "    defaultConfig {\n"
        f'        applicationId "{pkg}"\n'
        "        minSdk 24\n"
        "        targetSdk 37\n"
        "        versionCode 1\n"
        '        versionName "1.0"\n'
        "    }\n"
        "    buildTypes {\n"
        "        release {\n"
        "            minifyEnabled false\n"
        "            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'\n"
        "        }\n"
        "    }\n"
        "    compileOptions {\n"
        "        sourceCompatibility JavaVersion.VERSION_17\n"
        "        targetCompatibility JavaVersion.VERSION_17\n"
        "    }\n"
        f"{features}"
        "}\n\n"
        "kotlin {\n"
        "    compilerOptions {\n"
        "        jvmTarget.set(JvmTarget.JVM_17)\n"
        "    }\n"
        "}\n\n"
        "dependencies {\n"
        f"{deps}"
        "}\n"
    )


def f_manifest(theme_name):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n\n'
        "    <application\n"
        '        android:allowBackup="true"\n'
        '        android:icon="@mipmap/ic_launcher"\n'
        '        android:label="@string/app_name"\n'
        '        android:roundIcon="@mipmap/ic_launcher_round"\n'
        '        android:supportsRtl="true"\n'
        f'        android:theme="@style/{theme_name}">\n'
        "        <activity\n"
        '            android:name=".MainActivity"\n'
        '            android:exported="true"\n'
        f'            android:theme="@style/{theme_name}">\n'
        "            <intent-filter>\n"
        '                <action android:name="android.intent.action.MAIN" />\n'
        '                <category android:name="android.intent.category.LAUNCHER" />\n'
        "            </intent-filter>\n"
        "        </activity>\n"
        "    </application>\n\n"
        "</manifest>\n"
    )


def f_strings(name):
    return (
        "<resources>\n"
        f"    <string name=\"app_name\">{name}</string>\n"
        "</resources>\n"
    )


# ---- Compose theme files (mirror Android Studio's ui/theme/* ) ----------------

def f_color_kt(pkg):
    return (
        f"package {pkg}.ui.theme\n\n"
        "import androidx.compose.ui.graphics.Color\n\n"
        "val Purple80 = Color(0xFFD0BCFF)\n"
        "val PurpleGrey80 = Color(0xFFCCC2DC)\n"
        "val Pink80 = Color(0xFFEFB8C8)\n\n"
        "val Purple40 = Color(0xFF6650a4)\n"
        "val PurpleGrey40 = Color(0xFF625b71)\n"
        "val Pink40 = Color(0xFF7D5260)\n"
    )


def f_type_kt(pkg):
    return (
        f"package {pkg}.ui.theme\n\n"
        "import androidx.compose.material3.Typography\n"
        "import androidx.compose.ui.text.TextStyle\n"
        "import androidx.compose.ui.text.font.FontFamily\n"
        "import androidx.compose.ui.text.font.FontWeight\n"
        "import androidx.compose.ui.unit.sp\n\n"
        "// Set of Material typography styles to start with\n"
        "val Typography = Typography(\n"
        "    bodyLarge = TextStyle(\n"
        "        fontFamily = FontFamily.Default,\n"
        "        fontWeight = FontWeight.Normal,\n"
        "        fontSize = 16.sp,\n"
        "        lineHeight = 24.sp,\n"
        "        letterSpacing = 0.5.sp\n"
        "    )\n"
        ")\n"
    )


def f_theme_kt(pkg, theme_prefix):
    return (
        f"package {pkg}.ui.theme\n\n"
        "import android.os.Build\n"
        "import androidx.compose.foundation.isSystemInDarkTheme\n"
        "import androidx.compose.material3.MaterialTheme\n"
        "import androidx.compose.material3.darkColorScheme\n"
        "import androidx.compose.material3.dynamicDarkColorScheme\n"
        "import androidx.compose.material3.dynamicLightColorScheme\n"
        "import androidx.compose.material3.lightColorScheme\n"
        "import androidx.compose.runtime.Composable\n"
        "import androidx.compose.ui.platform.LocalContext\n\n"
        "private val DarkColorScheme = darkColorScheme(\n"
        "    primary = Purple80,\n"
        "    secondary = PurpleGrey80,\n"
        "    tertiary = Pink80\n"
        ")\n\n"
        "private val LightColorScheme = lightColorScheme(\n"
        "    primary = Purple40,\n"
        "    secondary = PurpleGrey40,\n"
        "    tertiary = Pink40\n"
        ")\n\n"
        "@Composable\n"
        f"fun {theme_prefix}Theme(\n"
        "    darkTheme: Boolean = isSystemInDarkTheme(),\n"
        "    // Dynamic color is available on Android 12+\n"
        "    dynamicColor: Boolean = true,\n"
        "    content: @Composable () -> Unit\n"
        ") {\n"
        "    val colorScheme = when {\n"
        "        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {\n"
        "            val context = LocalContext.current\n"
        "            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)\n"
        "        }\n\n"
        "        darkTheme -> DarkColorScheme\n"
        "        else -> LightColorScheme\n"
        "    }\n\n"
        "    MaterialTheme(\n"
        "        colorScheme = colorScheme,\n"
        "        typography = Typography,\n"
        "        content = content\n"
        "    )\n"
        "}\n"
    )


def f_themes_compose(theme_name):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources>\n'
        f'    <style name="{theme_name}" parent="android:Theme.Material.Light.NoActionBar" />\n'
        "</resources>\n"
    )


def f_mainactivity_compose(pkg, theme_prefix):
    return (
        f"package {pkg}\n\n"
        "import android.os.Bundle\n"
        "import androidx.activity.ComponentActivity\n"
        "import androidx.activity.compose.setContent\n"
        "import androidx.activity.enableEdgeToEdge\n"
        "import androidx.compose.foundation.layout.fillMaxSize\n"
        "import androidx.compose.foundation.layout.padding\n"
        "import androidx.compose.material3.Scaffold\n"
        "import androidx.compose.material3.Text\n"
        "import androidx.compose.runtime.Composable\n"
        "import androidx.compose.ui.Modifier\n"
        "import androidx.compose.ui.tooling.preview.Preview\n"
        f"import {pkg}.ui.theme.{theme_prefix}Theme\n\n"
        "class MainActivity : ComponentActivity() {\n"
        "    override fun onCreate(savedInstanceState: Bundle?) {\n"
        "        super.onCreate(savedInstanceState)\n"
        "        enableEdgeToEdge()\n"
        "        setContent {\n"
        f"            {theme_prefix}Theme {{\n"
        "                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->\n"
        "                    Greeting(\n"
        '                        name = "Android",\n'
        "                        modifier = Modifier.padding(innerPadding)\n"
        "                    )\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        "@Composable\n"
        "fun Greeting(name: String, modifier: Modifier = Modifier) {\n"
        '    Text(\n'
        '        text = "Hello $name!",\n'
        "        modifier = modifier\n"
        "    )\n"
        "}\n\n"
        "@Preview(showBackground = true)\n"
        "@Composable\n"
        "fun GreetingPreview() {\n"
        f"    {theme_prefix}Theme {{\n"
        '        Greeting("Android")\n'
        "    }\n"
        "}\n"
    )


# ---- Views / XML resources (mirror Android Studio's Empty Views Activity) ------

def f_colors_xml():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        '    <color name="black">#FF000000</color>\n'
        '    <color name="white">#FFFFFFFF</color>\n'
        '    <color name="purple_200">#FFBB86FC</color>\n'
        '    <color name="purple_500">#FF6200EE</color>\n'
        '    <color name="purple_700">#FF3700B3</color>\n'
        '    <color name="teal_200">#FF03DAC5</color>\n'
        '    <color name="teal_700">#FF018786</color>\n'
        "</resources>\n"
    )


def f_themes_xml(theme_name, night=False):
    primary = "@color/purple_200" if night else "@color/purple_500"
    primary_variant = "@color/purple_700"
    on_primary = "@color/black" if night else "@color/white"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources xmlns:tools="http://schemas.android.com/tools">\n'
        f'    <style name="{theme_name}" parent="Theme.Material3.DayNight.NoActionBar">\n'
        f'        <item name="colorPrimary">{primary}</item>\n'
        f'        <item name="colorPrimaryVariant">{primary_variant}</item>\n'
        f'        <item name="colorOnPrimary">{on_primary}</item>\n'
        '        <item name="colorSecondary">@color/teal_200</item>\n'
        '        <item name="colorSecondaryVariant">@color/teal_700</item>\n'
        '        <item name="colorOnSecondary">@color/black</item>\n'
        "    </style>\n"
        "</resources>\n"
    )


def f_mainactivity_xml(pkg):
    return (
        f"package {pkg}\n\n"
        "import android.os.Bundle\n"
        "import androidx.appcompat.app.AppCompatActivity\n"
        f"import {pkg}.databinding.ActivityMainBinding\n\n"
        "class MainActivity : AppCompatActivity() {\n"
        "    private lateinit var binding: ActivityMainBinding\n\n"
        "    override fun onCreate(savedInstanceState: Bundle?) {\n"
        "        super.onCreate(savedInstanceState)\n"
        "        binding = ActivityMainBinding.inflate(layoutInflater)\n"
        "        setContentView(binding.root)\n"
        '        binding.textView.text = "Hello Termux!"\n'
        "    }\n"
        "}\n"
    )


def f_layout_xml():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<androidx.constraintlayout.widget.ConstraintLayout "
        'xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    xmlns:app="http://schemas.android.com/apk/res-auto"\n'
        '    xmlns:tools="http://schemas.android.com/tools"\n'
        '    android:layout_width="match_parent"\n'
        '    android:layout_height="match_parent"\n'
        '    tools:context=".MainActivity">\n\n'
        "    <TextView\n"
        '        android:id="@+id/textView"\n'
        '        android:layout_width="wrap_content"\n'
        '        android:layout_height="wrap_content"\n'
        '        android:text="Hello World!"\n'
        '        app:layout_constraintBottom_toBottomOf="parent"\n'
        '        app:layout_constraintEnd_toEndOf="parent"\n'
        '        app:layout_constraintStart_toStartOf="parent"\n'
        '        app:layout_constraintTop_toTopOf="parent" />\n\n'
        "</androidx.constraintlayout.widget.ConstraintLayout>\n"
    )


def f_backup_rules():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<full-backup-content>\n"
        "</full-backup-content>\n"
    )


def f_data_extraction_rules():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<data-extraction-rules>\n"
        "    <cloud-backup>\n"
        "    </cloud-backup>\n"
        "</data-extraction-rules>\n"
    )


# ---- launcher icons (vector only — no binaries, builds on minSdk 24) ----------

def f_ic_background():
    return (
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        '    <path android:fillColor="#3DDC84" android:pathData="M0,0h108v108h-108z" />\n'
        "</vector>\n"
    )


def f_ic_foreground():
    # A simple centred white circle (108x108 canvas, safe zone is the middle ~72dp).
    return (
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        '    <path android:fillColor="#FFFFFF"\n'
        '        android:pathData="M54,32 A22,22 0 1 0 54,76 A22,22 0 1 0 54,32 Z" />\n'
        "</vector>\n"
    )


def f_ic_adaptive():
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@drawable/ic_launcher_background" />\n'
        '    <foreground android:drawable="@drawable/ic_launcher_foreground" />\n'
        '    <monochrome android:drawable="@drawable/ic_launcher_foreground" />\n'
        "</adaptive-icon>\n"
    )


def f_ic_fallback():
    # Full icon as a single vector for API 24–25 (no adaptive-icon there).
    return (
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        '    <path android:fillColor="#3DDC84" android:pathData="M0,0h108v108h-108z" />\n'
        '    <path android:fillColor="#FFFFFF"\n'
        '        android:pathData="M54,32 A22,22 0 1 0 54,76 A22,22 0 1 0 54,32 Z" />\n'
        "</vector>\n"
    )


def f_proguard():
    return "# Add project specific ProGuard rules here.\n"


def copy_wrapper(root):
    src = WRAPPER_SRC
    ok = True
    for rel in ("gradlew", "gradlew.bat",
                "gradle/wrapper/gradle-wrapper.jar",
                "gradle/wrapper/gradle-wrapper.properties"):
        s = os.path.join(src, rel)
        d = os.path.join(root, rel)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
        else:
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--template", required=True, choices=["compose", "xml"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--package")
    ap.add_argument("--sdk", default=os.environ.get(
        "ANDROID_HOME", "/data/data/com.termux/files/home/android-sdk"))
    args = ap.parse_args()

    name = args.name.strip()
    compose = args.template == "compose"
    safe_name = sanitize_pkg_segment(name)
    pkg = args.package or f"com.example.{safe_name}"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", pkg):
        die(f"invalid package name: {pkg}")

    theme_prefix = pascal_case(name)
    theme_name = f"Theme.{theme_prefix}"

    root = os.path.abspath(os.path.join(os.path.expanduser(args.dir), name))
    if os.path.exists(root) and os.listdir(root):
        die(f"target directory exists and is not empty: {root}")

    pkg_path = pkg.replace(".", "/")
    src_main = os.path.join(root, "app/src/main")
    code_dir = os.path.join(src_main, "java", pkg_path)
    res = os.path.join(src_main, "res")

    print(f"{C['c']}Scaffolding {C['b']}{args.template}{C['e']}{C['c']} project "
          f"'{name}' ({pkg}){C['e']}")

    # root-level
    write(os.path.join(root, ".gitignore"), f_gitignore())
    write(os.path.join(root, "gradle.properties"), f_gradle_properties())
    write(os.path.join(root, "settings.gradle"), f_settings(name, compose))
    write(os.path.join(root, "build.gradle"), f_root_build(compose))
    write(os.path.join(root, "local.properties"), f"sdk.dir={args.sdk}\n")

    # app module
    write(os.path.join(root, "app/build.gradle"), f_app_build(pkg, compose))
    write(os.path.join(root, "app/proguard-rules.pro"), f_proguard())
    write(os.path.join(root, "app/.gitignore"), "/build\n")
    write(os.path.join(src_main, "AndroidManifest.xml"), f_manifest(theme_name))
    write(os.path.join(code_dir, "MainActivity.kt"),
          f_mainactivity_compose(pkg, theme_prefix) if compose else f_mainactivity_xml(pkg))
    write(os.path.join(res, "values/strings.xml"), f_strings(name))

    # backup/data-extraction stubs (present in every AS project)
    write(os.path.join(res, "xml/backup_rules.xml"), f_backup_rules())
    write(os.path.join(res, "xml/data_extraction_rules.xml"), f_data_extraction_rules())

    # launcher icons (adaptive on API 26+, vector fallback for 24–25)
    write(os.path.join(res, "drawable/ic_launcher_background.xml"), f_ic_background())
    write(os.path.join(res, "drawable/ic_launcher_foreground.xml"), f_ic_foreground())
    write(os.path.join(res, "mipmap-anydpi-v26/ic_launcher.xml"), f_ic_adaptive())
    write(os.path.join(res, "mipmap-anydpi-v26/ic_launcher_round.xml"), f_ic_adaptive())
    write(os.path.join(res, "mipmap/ic_launcher.xml"), f_ic_fallback())
    write(os.path.join(res, "mipmap/ic_launcher_round.xml"), f_ic_fallback())

    if compose:
        # ui/theme/{Color,Theme,Type}.kt — the Android Studio Compose theme package
        theme_dir = os.path.join(code_dir, "ui", "theme")
        write(os.path.join(theme_dir, "Color.kt"), f_color_kt(pkg))
        write(os.path.join(theme_dir, "Type.kt"), f_type_kt(pkg))
        write(os.path.join(theme_dir, "Theme.kt"), f_theme_kt(pkg, theme_prefix))
        write(os.path.join(res, "values/themes.xml"), f_themes_compose(theme_name))
    else:
        write(os.path.join(res, "layout/activity_main.xml"), f_layout_xml())
        write(os.path.join(res, "values/colors.xml"), f_colors_xml())
        write(os.path.join(res, "values/themes.xml"), f_themes_xml(theme_name, night=False))
        write(os.path.join(res, "values-night/themes.xml"), f_themes_xml(theme_name, night=True))

    # gradle wrapper (for Android Studio compatibility)
    if copy_wrapper(root):
        print(f"{C['g']}✔ gradle wrapper copied{C['e']}")
    else:
        print(f"{C['y']}! wrapper source not found; run 'gradle wrapper' in the "
              f"project if you need it for Studio{C['e']}")

    print(f"{C['g']}✔ created {root}{C['e']}")
    print(root)  # last line = path (consumed by caller)


if __name__ == "__main__":
    main()
