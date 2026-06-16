#!/usr/bin/env python3
"""
studio_new.py - scaffold a new Android project that builds with the Termux toolchain.

Usage: studio_new.py --name NAME --template {compose|xml} --dir PARENT_DIR [--package PKG]

Mirrors the proven version set on this device (AGP 9.2.1 / Gradle 9.5 / compileSdk 36,
AGP built-in Kotlin). Produces a layout Android Studio also opens cleanly.
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


def f_manifest(compose):
    theme = "@style/Theme.App"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n\n'
        "    <application\n"
        '        android:allowBackup="true"\n'
        '        android:label="@string/app_name"\n'
        '        android:supportsRtl="true"\n'
        f'        android:theme="{theme}">\n'
        "        <activity\n"
        '            android:name=".MainActivity"\n'
        '            android:exported="true">\n'
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


def f_themes(compose):
    if compose:
        parent = "android:Theme.Material.Light.NoActionBar"
    else:
        parent = "Theme.Material3.DayNight.NoActionBar"
    return (
        "<resources>\n"
        f'    <style name="Theme.App" parent="{parent}" />\n'
        "</resources>\n"
    )


def f_mainactivity_compose(pkg):
    return (
        f"package {pkg}\n\n"
        "import android.os.Bundle\n"
        "import androidx.activity.ComponentActivity\n"
        "import androidx.activity.compose.setContent\n"
        "import androidx.compose.foundation.layout.fillMaxSize\n"
        "import androidx.compose.foundation.layout.padding\n"
        "import androidx.compose.material3.MaterialTheme\n"
        "import androidx.compose.material3.Scaffold\n"
        "import androidx.compose.material3.Text\n"
        "import androidx.compose.runtime.Composable\n"
        "import androidx.compose.ui.Modifier\n"
        "import androidx.compose.ui.tooling.preview.Preview\n\n"
        "class MainActivity : ComponentActivity() {\n"
        "    override fun onCreate(savedInstanceState: Bundle?) {\n"
        "        super.onCreate(savedInstanceState)\n"
        "        setContent {\n"
        "            MaterialTheme {\n"
        "                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->\n"
        '                    Greeting("Termux", Modifier.padding(padding))\n'
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        "@Composable\n"
        "fun Greeting(name: String, modifier: Modifier = Modifier) {\n"
        '    Text(text = "Hello $name!", modifier = modifier)\n'
        "}\n\n"
        "@Preview(showBackground = true)\n"
        "@Composable\n"
        "fun GreetingPreview() {\n"
        "    MaterialTheme {\n"
        '        Greeting("Termux")\n'
        "    }\n"
        "}\n"
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
        '    android:layout_width="match_parent"\n'
        '    android:layout_height="match_parent">\n\n'
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
    pkg = args.package or f"com.termux.{safe_name}"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", pkg):
        die(f"invalid package name: {pkg}")

    root = os.path.abspath(os.path.join(os.path.expanduser(args.dir), name))
    if os.path.exists(root) and os.listdir(root):
        die(f"target directory exists and is not empty: {root}")

    pkg_path = pkg.replace(".", "/")
    src_main = os.path.join(root, "app/src/main")

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
    write(os.path.join(src_main, "AndroidManifest.xml"), f_manifest(compose))
    write(os.path.join(src_main, f"java/{pkg_path}/MainActivity.kt"),
          f_mainactivity_compose(pkg) if compose else f_mainactivity_xml(pkg))
    write(os.path.join(src_main, "res/values/strings.xml"), f_strings(name))
    write(os.path.join(src_main, "res/values/themes.xml"), f_themes(compose))
    if not compose:
        write(os.path.join(src_main, "res/layout/activity_main.xml"), f_layout_xml())

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
