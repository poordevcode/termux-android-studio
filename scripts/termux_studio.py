#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time
import readline
import glob
import shutil
import shlex
import getpass
import json
import re

# Where per-project signing keystore details are remembered between release builds.
KEYSTORE_DIR = os.path.expanduser("~/.studio/keystores")
# Last project opened in the TUI — auto-reopened on the next `studio start` (no path arg).
LAST_PROJECT_FILE = os.path.expanduser("~/.studio/last_project")
# Fallback keytool if it isn't on PATH (matches the JDK the studio CLI pins).
KEYTOOL_FALLBACK = "/data/data/com.termux/files/usr/lib/jvm/java-21-openjdk/bin/keytool"

# Color definitions
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

# Path Autocomplete Helper
def path_completer(text, state):
    # Expand user home directory
    expanded = os.path.expanduser(text)
    # Get matches using glob
    matches = glob.glob(expanded + '*')
    
    # Format matches nicely back to what user typed
    results = []
    for m in matches:
        if os.path.isdir(m):
            results.append(m + '/')
        else:
            results.append(m)
            
    try:
        return results[state]
    except IndexError:
        return None

# Common Gradle Tasks list
COMMON_GRADLE_TASKS = [
    "assemble", "assembleDebug", "assembleRelease", "clean", "build", "check", "test", 
    "installDebug", "connectedAndroidTest", "lint", "dependencies", "help", "tasks"
]

def gradle_task_completer(text, state):
    options = [task for task in COMMON_GRADLE_TASKS if task.startswith(text)]
    try:
        return options[state]
    except IndexError:
        return None

# Configure Readline
readline.set_completer_delims(' \t\n;')
readline.parse_and_bind("tab: complete")
readline.set_completer(path_completer)

class TermuxStudio:
    def __init__(self):
        self.project_path = ""
        self.status = "No Project Loaded"
        self.android_home = os.environ.get("ANDROID_HOME", "/data/data/com.termux/files/home/android-sdk")
        self.java_home = os.environ.get("JAVA_HOME", "")
        self.is_running = True

    def remember_project(self):
        """Persist the current project so the next `studio start` (with no path) reopens it."""
        if not self.project_path:
            return
        try:
            os.makedirs(os.path.dirname(LAST_PROJECT_FILE), exist_ok=True)
            with open(LAST_PROJECT_FILE, "w") as f:
                f.write(self.project_path + "\n")
        except Exception:
            pass

    @staticmethod
    def last_project():
        """The last project path if it still exists and looks like a Gradle project, else None."""
        try:
            with open(LAST_PROJECT_FILE) as f:
                p = f.read().strip()
        except Exception:
            return None
        if p and os.path.isdir(p) and (
                os.path.exists(os.path.join(p, "build.gradle"))
                or os.path.exists(os.path.join(p, "build.gradle.kts"))
                or os.path.exists(os.path.join(p, "settings.gradle"))
                or os.path.exists(os.path.join(p, "settings.gradle.kts"))):
            return p
        return None

    def open_project(self, path, status="Project Loaded"):
        """Set the active project, create local.properties if missing, and remember it."""
        self.project_path = os.path.abspath(os.path.expanduser(path))
        self.status = status
        local_props = os.path.join(self.project_path, "local.properties")
        if not os.path.exists(local_props):
            try:
                with open(local_props, "w") as f:
                    f.write(f"sdk.dir={self.android_home}\n")
            except Exception:
                pass
        self.remember_project()

    def clear_screen(self):
        os.system('clear')

    def print_header(self):
        self.clear_screen()
        print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════════╗{Colors.END}")
        print(f"{Colors.BLUE}║                 {Colors.BOLD}{Colors.CYAN}TERMUX STUDIO - Android IDE v1.0{Colors.END}{Colors.BLUE}             ║{Colors.END}")
        print(f"{Colors.BLUE}╠══════════════════════════════════════════════════════════════╣{Colors.END}")
        
        # Format project path display
        path_disp = self.project_path if self.project_path else "None (Use Option 1 to load)"
        if len(path_disp) > 42:
            path_disp = "..." + path_disp[-39:]
            
        print(f"{Colors.BLUE}║ {Colors.BOLD}Project:{Colors.END} {path_disp:<49} {Colors.BLUE}║{Colors.END}")
        print(f"{Colors.BLUE}║ {Colors.BOLD}Status: {Colors.END} {self.status:<50} {Colors.BLUE}║{Colors.END}")
        print(f"{Colors.BLUE}║ {Colors.BOLD}SDK Path:{Colors.END} {self.android_home:<49} {Colors.BLUE}║{Colors.END}")
        print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════════╝{Colors.END}")
        print()

    def run_gradle_task(self, task_name):
        if not self.project_path:
            print(f"{Colors.RED}Error: No project loaded!{Colors.END}")
            input("\nPress Enter to continue...")
            return False

        # Parse task name into separate arguments to support flags and multiple tasks
        args = shlex.split(task_name)

        # Delegate to the 'studio' CLI so builds get the Termux adaptations:
        # system Gradle (gradlew is noexec on /storage), the native aapt2 override, and
        # the transient move/restore of the Studio daemon-JVM pin. Repo stays pristine.
        cmd = ["studio", "build", self.project_path] + args

        # Setup environment variables
        env = os.environ.copy()
        env["ANDROID_HOME"] = self.android_home
        env["ANDROID_SDK_ROOT"] = self.android_home
        env["JAVA_OPTS"] = "-Djava.net.preferIPv4Stack=true"

        print(f"\n{Colors.YELLOW}Executing: {' '.join(cmd)}{Colors.END}")
        print(f"{Colors.CYAN}(press Ctrl-C to cancel the build){Colors.END}\n")
        self.status = f"Running {task_name}..."

        # Start command in its own session so Ctrl-C can stop the whole gradle process tree
        # (studio → gradle → workers), not just the python reader.
        process = None
        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.project_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=True,
            )

            # Read stdout line by line and print
            while True:
                line = process.stdout.readline()
                if not line:
                    break

                # Highlight and print lines
                clean_line = line.strip()
                if "FAILED" in clean_line or "ERROR" in clean_line or "Exception" in clean_line:
                    print(f"{Colors.RED}{line}{Colors.END}", end="")
                elif "WARNING" in clean_line or "Warning" in clean_line:
                    print(f"{Colors.YELLOW}{line}{Colors.END}", end="")
                elif clean_line.startswith("> Task"):
                    print(f"{Colors.GREEN}{line}{Colors.END}", end="")
                elif "Build successful" in clean_line or "SUCCESSFUL" in clean_line:
                    print(f"{Colors.BOLD}{Colors.GREEN}{line}{Colors.END}", end="")
                else:
                    print(line, end="")

            process.wait()

            if process.returncode == 0:
                self.status = f"{task_name} successful!"
                print(f"\n{Colors.BOLD}{Colors.GREEN}✔ Command executed successfully!{Colors.END}")
                return True
            else:
                self.status = f"{task_name} failed (exit code {process.returncode})"
                print(f"\n{Colors.BOLD}{Colors.RED}✘ Command failed with exit code {process.returncode}!{Colors.END}")
                return False

        except KeyboardInterrupt:
            self._terminate_build(process)
            self.status = "Build cancelled"
            print(f"\n{Colors.BOLD}{Colors.YELLOW}■ Build cancelled.{Colors.END}")
            return False
        except Exception as e:
            self.status = f"Execution error"
            print(f"\n{Colors.BOLD}{Colors.RED}Error executing command: {e}{Colors.END}")
            return False

    @staticmethod
    def _terminate_build(process):
        """Stop a running build's whole process group (gradle + workers). Escalates
        SIGINT → SIGTERM → SIGKILL across the group so no straggler (e.g. a background
        worker that ignores SIGINT) is left behind."""
        if not process or process.poll() is not None:
            return
        import signal
        try:
            pgid = os.getpgid(process.pid)
        except Exception:
            pgid = None

        def sig_all(sig):
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    process.send_signal(sig)
            except Exception:
                pass

        for sig, wait in ((signal.SIGINT, 4), (signal.SIGTERM, 4), (signal.SIGKILL, 3)):
            sig_all(sig)
            try:
                process.wait(timeout=wait)
            except Exception:
                continue
            # parent is gone; still SIGKILL the group once more to clear any stragglers.
            if sig is not signal.SIGKILL:
                sig_all(signal.SIGKILL)
            return

    def create_new_project(self):
        self.print_header()
        print(f"{Colors.BOLD}Create New Android Project{Colors.END}\n")
        name = input(f"{Colors.CYAN}Project name: {Colors.END}").strip()
        if not name:
            return
        print("\nTemplate:")
        print(f"  1. {Colors.GREEN}Jetpack Compose{Colors.END} (modern Kotlin UI)")
        print(f"  2. {Colors.GREEN}Views / XML{Colors.END} (AppCompat + layouts + ViewBinding)")
        print("  0. Cancel")
        t = input(f"{Colors.CYAN}Choice (1/2): {Colors.END}").strip()
        if t == "0":
            return
        template = "--compose" if t == "1" else "--xml" if t == "2" else None
        if not template:
            print(f"{Colors.RED}Invalid template.{Colors.END}"); time.sleep(1.5); return

        # Package (applicationId) — default to com.example.<sanitized name>, like Android Studio.
        safe = re.sub(r"[^a-zA-Z0-9]", "", name).lower() or "app"
        if safe[0].isdigit():
            safe = "a" + safe
        default_pkg = f"com.example.{safe}"
        package = input(f"{Colors.CYAN}Package name [{default_pkg}]: {Colors.END}").strip() or default_pkg
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", package):
            print(f"{Colors.RED}Invalid package name (need at least two dot-separated segments, "
                  f"e.g. com.example.app).{Colors.END}"); time.sleep(2); return

        default_dir = os.path.join(os.path.expanduser("~"), "AndroidStudioProjects")
        parent = input(f"{Colors.CYAN}Parent directory [{default_dir}]: {Colors.END}").strip() or default_dir

        cmd = ["studio", "new", name, template, "--package", package, "--dir", parent]
        print(f"\n{Colors.YELLOW}Running: {' '.join(cmd)}{Colors.END}\n")
        try:
            subprocess.run(cmd)
            created = os.path.join(os.path.abspath(os.path.expanduser(parent)), name)
            if os.path.isdir(created):
                self.project_path = created
                self.status = "New project created & loaded"
                self.remember_project()
                print(f"\n{Colors.GREEN}Loaded new project: {created}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Failed: {e}{Colors.END}")
        input("\nPress Enter to continue...")

    def clone_from_vcs(self):
        self.print_header()
        print(f"{Colors.BOLD}Get Project from Version Control (Git){Colors.END}\n")
        url = input(f"{Colors.CYAN}Repository URL: {Colors.END}").strip()
        if not url:
            return
        default_dir = os.path.join(os.path.expanduser("~"), "AndroidStudioProjects")
        parent = input(f"{Colors.CYAN}Save into folder [{default_dir}]: {Colors.END}").strip() or default_dir

        # Predict the destination so we can load it after a live (streamed) clone.
        name = os.path.basename(url.rstrip("/"))
        if name.endswith(".git"):
            name = name[:-4]
        cloned = os.path.join(os.path.abspath(os.path.expanduser(parent)), name)

        cmd = ["studio", "clone", url, parent]
        print(f"\n{Colors.YELLOW}Running: {' '.join(cmd)}{Colors.END}\n")
        try:
            rc = subprocess.run(cmd).returncode
            if rc == 0 and os.path.isdir(cloned):
                self.project_path = cloned
                self.status = "Cloned & imported from VCS"
                self.remember_project()
                print(f"\n{Colors.GREEN}Loaded cloned project: {cloned}{Colors.END}")
            elif rc != 0:
                print(f"\n{Colors.RED}Clone failed (exit {rc}).{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Failed: {e}{Colors.END}")
        input("\nPress Enter to continue...")

    def load_project(self):
        self.print_header()
        print(f"{Colors.BOLD}Enter the absolute path to your Android project:{Colors.END}")
        print(f"(Press TAB for autocompletion)")
        
        path_input = input(f"{Colors.CYAN}Path: {Colors.END}").strip()
        if not path_input:
            return

        expanded_path = os.path.abspath(os.path.expanduser(path_input))
        
        if not os.path.exists(expanded_path):
            print(f"\n{Colors.RED}Directory does not exist: {expanded_path}{Colors.END}")
            time.sleep(2)
            return

        # Check if it has gradle files
        build_gradle = os.path.join(expanded_path, "build.gradle")
        build_gradle_kts = os.path.join(expanded_path, "build.gradle.kts")
        
        if not (os.path.exists(build_gradle) or os.path.exists(build_gradle_kts)):
            print(f"\n{Colors.YELLOW}Warning: No build.gradle or build.gradle.kts found in this directory.{Colors.END}")
            confirm = input("Are you sure this is a Gradle Android project? (y/N): ").strip().lower()
            if confirm != 'y':
                return

        self.project_path = expanded_path
        self.status = "Project Loaded"

        # Configure local.properties
        local_properties = os.path.join(self.project_path, "local.properties")
        if not os.path.exists(local_properties):
            print(f"\n{Colors.CYAN}Creating local.properties with sdk.dir={self.android_home}...{Colors.END}")
            try:
                with open(local_properties, 'w') as f:
                    f.write(f"sdk.dir={self.android_home}\n")
            except Exception as e:
                print(f"{Colors.RED}Could not write local.properties: {e}{Colors.END}")

        self.remember_project()
        print(f"\n{Colors.GREEN}Successfully loaded project: {self.project_path}{Colors.END}")
        time.sleep(1.5)

    def sync_project(self):
        self.print_header()
        if not self.project_path:
            print(f"{Colors.RED}Please load a project first!{Colors.END}")
            time.sleep(1.5)
            return
            
        print(f"{Colors.BOLD}Syncing project dependencies...{Colors.END}")
        # Run gradle tasks or help as a sync indicator
        self.run_gradle_task("help")
        input("\nPress Enter to continue...")

    def run_custom_gradle_command(self):
        self.print_header()
        if not self.project_path:
            print(f"{Colors.RED}Please load a project first!{Colors.END}")
            time.sleep(1.5)
            return

        # Temporarily switch completer to gradle tasks
        old_completer = readline.get_completer()
        readline.set_completer(gradle_task_completer)
        
        print(f"{Colors.BOLD}Enter custom Gradle task(s) and flags to run (e.g. assembleDebug, clean build, --info):{Colors.END}")
        print("(Press TAB for common task suggestions)")
        print()
        
        try:
            custom_input = input(f"{Colors.CYAN}gradlew {Colors.END}").strip()
        except (KeyboardInterrupt, EOFError):
            custom_input = ""
            
        # Restore old completer
        readline.set_completer(old_completer)
        
        if not custom_input:
            return
            
        self.run_gradle_task(custom_input)
        input("\nPress Enter to continue...")

    def build_project(self):
        self.print_header()
        if not self.project_path:
            print(f"{Colors.RED}Please load a project first!{Colors.END}")
            time.sleep(1.5)
            return

        print(f"{Colors.BOLD}Select Build Action:{Colors.END}")
        print("1. Assemble Debug APK (assembleDebug)")
        print("2. Assemble Release APK (assembleRelease)")
        print("3. Clean Project (clean)")
        print("4. Clean and Assemble Debug")
        print(f"5. {Colors.GREEN}Run on Device ▶{Colors.END} (build + install + launch, like Android Studio)")
        print("6. Reset remembered release settings (keystore / name / skip-prompts)")
        print("7. Back to Main Menu")
        print()

        choice = input(f"{Colors.CYAN}Choice (1-7): {Colors.END}").strip()

        if choice == "5":
            self.run_on_device()
            return
        if choice == "6":
            self.reset_release_memory()
            return
        if choice == "1":
            success = self.run_gradle_task("assembleDebug")
            if success:
                self.locate_and_offer_apks()
            else:
                input("\nPress Enter to continue...")
        elif choice == "2":
            success = self.assemble_release()
            if success:
                self.locate_and_offer_apks()
            else:
                input("\nPress Enter to continue...")
        elif choice == "3":
            self.run_gradle_task("clean")
            input("\nPress Enter to continue...")
        elif choice == "4":
            if self.run_gradle_task("clean"):
                success = self.run_gradle_task("assembleDebug")
                if success:
                    self.locate_and_offer_apks()
                else:
                    input("\nPress Enter to continue...")
            else:
                input("\nPress Enter to continue...")
        else:
            return

    # ---------------------------------------------------------- keystore helpers

    def _keytool(self):
        """Resolve the keytool binary (PATH first, then the pinned JDK)."""
        return shutil.which("keytool") or KEYTOOL_FALLBACK

    def _keystore_config_file(self):
        """Per-project file where remembered keystore details are stored (mode 600)."""
        os.makedirs(KEYSTORE_DIR, exist_ok=True)
        key = self.project_path.replace("/", "_").replace(" ", "_")
        return os.path.join(KEYSTORE_DIR, key + ".json")

    def load_release_config(self):
        """Raw remembered release settings for this project — keystore + apk name + the
        'auto' (skip-prompts) flag — or None. No validation here; callers check as needed."""
        f = self._keystore_config_file()
        if os.path.isfile(f):
            try:
                with open(f) as fh:
                    return json.load(fh)
            except Exception:
                return None
        return None

    def save_release_config(self, data):
        """Persist release settings for next time (plaintext, on-device, perms 600)."""
        f = self._keystore_config_file()
        try:
            with open(f, "w") as fh:
                json.dump(data, fh)
            os.chmod(f, 0o600)
            return True
        except Exception as e:
            print(f"{Colors.RED}Could not save release settings: {e}{Colors.END}")
            return False

    def reset_release_memory(self):
        """Forget the remembered release settings (keystore/name/skip) for this project."""
        self.print_header()
        if not self.project_path:
            print(f"{Colors.RED}Please load a project first!{Colors.END}")
            time.sleep(1.5)
            return
        f = self._keystore_config_file()
        if os.path.isfile(f):
            try:
                os.remove(f)
                print(f"{Colors.GREEN}Remembered release settings cleared for this project.{Colors.END}")
                print(f"{Colors.CYAN}The next release build will ask for the keystore + name again.{Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}Could not clear: {e}{Colors.END}")
        else:
            print(f"{Colors.YELLOW}No remembered release settings for this project.{Colors.END}")
        input("\nPress Enter to continue...")

    def _release_task(self, ks, custom_name):
        """Compose the `assembleRelease` gradle command. ks=None signs with the debug keystore."""
        parts = ["assembleRelease"]
        if ks:
            parts += ["--keystore", ks["path"], "--ks-pass", ks["store_pass"],
                      "--ks-alias", ks["alias"], "--key-pass", ks["key_pass"]]
        if custom_name:
            parts += ["--apk-name", custom_name]
        return " ".join(shlex.quote(p) for p in parts)

    def _maybe_remember_release(self, ks, custom_name):
        """Offer to persist the release settings, optionally skipping all prompts next time."""
        print(f"\n{Colors.BOLD}Remember these release settings for next time?{Colors.END}")
        print("  1. No")
        print("  2. Remember keystore + name (still confirm each build)")
        print(f"  3. {Colors.GREEN}Remember everything & skip prompts{Colors.END} — build directly next time")
        c = input(f"{Colors.CYAN}Choice [1]: {Colors.END}").strip() or "1"
        if c not in ("2", "3"):
            return
        data = {"apk_name": custom_name, "auto": (c == "3")}
        if ks:
            data.update({"path": ks["path"], "store_pass": ks["store_pass"],
                         "alias": ks["alias"], "key_pass": ks["key_pass"]})
        if self.save_release_config(data):
            if c == "3":
                print(f"{Colors.GREEN}Saved — the next release build will run directly with these settings.{Colors.END}")
            else:
                print(f"{Colors.GREEN}Saved keystore + name.{Colors.END}")
            print(f"{Colors.YELLOW}(stored locally with 600 perms; clear it via Build menu → "
                  f"'Reset remembered release settings'){Colors.END}")

    def list_keystore_aliases(self, ks_path, store_pass):
        """List key aliases in a keystore. Returns a list, or None if the store password
        is wrong / keytool fails (so callers can distinguish 'empty' from 'auth failed')."""
        try:
            res = subprocess.run(
                [self._keytool(), "-list", "-keystore", ks_path, "-storepass", store_pass],
                capture_output=True, text=True)
        except Exception as e:
            print(f"{Colors.RED}keytool failed: {e}{Colors.END}")
            return None
        if res.returncode != 0:
            return None
        aliases = []
        for line in res.stdout.splitlines():
            if "PrivateKeyEntry" in line or "trustedCertEntry" in line:
                aliases.append(line.split(",")[0].strip())
        return aliases

    def select_alias(self, ks_path, store_pass):
        """After the store password is entered, show the keystore's aliases and let the
        user pick one. Returns the chosen alias, or None on failure."""
        aliases = self.list_keystore_aliases(ks_path, store_pass)
        if aliases is None:
            print(f"\n{Colors.RED}Could not read the keystore — wrong store password?{Colors.END}")
            return None
        if not aliases:
            print(f"{Colors.YELLOW}No key aliases reported; enter it manually.{Colors.END}")
            return input(f"{Colors.CYAN}Key alias: {Colors.END}").strip() or None
        if len(aliases) == 1:
            print(f"{Colors.GREEN}Using the only alias in this keystore: {aliases[0]}{Colors.END}")
            return aliases[0]
        print(f"\n{Colors.BOLD}Aliases found in this keystore:{Colors.END}")
        for i, a in enumerate(aliases, 1):
            print(f"  {i}. {a}")
        sel = input(f"{Colors.CYAN}Select alias (1-{len(aliases)}): {Colors.END}").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(aliases):
            return aliases[int(sel) - 1]
        print(f"{Colors.RED}Invalid selection.{Colors.END}")
        return None

    def create_keystore(self):
        """Create a brand-new release keystore step by step (path, passwords, alias, and
        certificate identity). Returns signing details dict, or None on failure/cancel."""
        self.print_header()
        print(f"{Colors.BOLD}Create a New Release Keystore{Colors.END}")
        print(f"{Colors.CYAN}(type 0 at the path prompt to cancel){Colors.END}\n")
        default_dir = os.path.join(os.path.expanduser("~"), "keystores")
        default_path = os.path.join(default_dir, "release.jks")
        path_in = input(f"{Colors.CYAN}New keystore path [{default_path}]: {Colors.END}").strip()
        if path_in == "0":
            print(f"{Colors.YELLOW}Cancelled.{Colors.END}")
            return None
        path = path_in or default_path
        ks_path = os.path.abspath(os.path.expanduser(path))
        if os.path.exists(ks_path):
            print(f"{Colors.RED}A file already exists at {ks_path} — choose another path.{Colors.END}")
            return None
        os.makedirs(os.path.dirname(ks_path), exist_ok=True)

        store_pass = getpass.getpass("Keystore (store) password: ")
        if len(store_pass) < 6:
            print(f"{Colors.RED}Store password must be at least 6 characters.{Colors.END}")
            return None
        alias = input(f"{Colors.CYAN}Key alias [release]: {Colors.END}").strip() or "release"
        key_pass = getpass.getpass("Key password [Enter = same as store]: ") or store_pass
        validity = input(f"{Colors.CYAN}Validity in days [10000]: {Colors.END}").strip() or "10000"

        print(f"\n{Colors.BOLD}Certificate identity (all optional — Enter to skip):{Colors.END}")
        cn = input(f"{Colors.CYAN}  Your name (CN): {Colors.END}").strip()
        ou = input(f"{Colors.CYAN}  Organizational unit (OU): {Colors.END}").strip()
        org = input(f"{Colors.CYAN}  Organization (O): {Colors.END}").strip()
        city = input(f"{Colors.CYAN}  City/Locality (L): {Colors.END}").strip()
        state = input(f"{Colors.CYAN}  State/Province (ST): {Colors.END}").strip()
        country = input(f"{Colors.CYAN}  Country code (C, e.g. US): {Colors.END}").strip()
        dn_parts = [f"{k}={v}" for k, v in
                    [("CN", cn), ("OU", ou), ("O", org), ("L", city), ("ST", state), ("C", country)] if v]
        dname = ", ".join(dn_parts) or "CN=Unknown"

        cmd = [self._keytool(), "-genkeypair", "-keystore", ks_path,
               "-storepass", store_pass, "-keypass", key_pass, "-alias", alias,
               "-keyalg", "RSA", "-keysize", "2048", "-validity", validity, "-dname", dname]
        print(f"\n{Colors.YELLOW}Generating keystore…{Colors.END}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"{Colors.RED}keytool failed:{Colors.END}\n{res.stderr.strip()}")
            return None
        print(f"{Colors.GREEN}✔ Created keystore: {ks_path} (alias '{alias}'){Colors.END}")
        return {"path": ks_path, "store_pass": store_pass, "alias": alias, "key_pass": key_pass}

    def assemble_release(self):
        """Assemble a signed release APK. Offers a remembered keystore, an existing keystore
        file (with alias selection after the store password is entered), creating a brand-new
        keystore step by step, or the debug keystore. The underlying `studio build` signs via
        AGP-injected properties and renames the output to <App Label>_<version>.apk."""
        self.print_header()
        print(f"{Colors.BOLD}Assemble Release APK{Colors.END}\n")

        cfg = self.load_release_config()

        # ── Fast path: settings remembered with "skip prompts" → build directly ──
        if cfg and cfg.get("auto"):
            ks = cfg if cfg.get("path") else None
            if ks and not os.path.isfile(ks["path"]):
                print(f"{Colors.YELLOW}Remembered keystore is gone ({ks['path']}); reconfiguring…{Colors.END}\n")
            else:
                nm = cfg.get("apk_name") or ""
                where = (f"{ks['path']}  alias {ks['alias']}" if ks else "debug keystore")
                print(f"{Colors.GREEN}Using remembered release settings (skip-prompts is ON):{Colors.END}")
                print(f"  keystore: {where}")
                print(f"  apk name: {nm or '<App Label>_<version>'}")
                print(f"{Colors.CYAN}  (reset via Build menu → 'Reset remembered release settings'){Colors.END}\n")
                return self.run_gradle_task(self._release_task(ks, nm))

        # ── Interactive flow ──
        # Pre-fill the name prompt with a remembered one (Enter reuses it).
        default_name = (cfg or {}).get("apk_name", "")
        custom_name = input(
            f"{Colors.CYAN}Release APK name [{default_name or '<App Label>_<version>'}]: {Colors.END}"
        ).strip() or default_name

        have_saved_ks = bool(cfg and cfg.get("path") and os.path.isfile(cfg["path"]))
        opts = []
        if have_saved_ks:
            opts.append(("saved", f"Use saved keystore: {cfg['path']} "
                                  f"(alias {Colors.GREEN}{cfg['alias']}{Colors.END})"))
        opts.append(("existing", "Use an existing keystore file (pick alias after password)"))
        opts.append(("create", "Create a new keystore (step by step)"))
        opts.append(("debug", "Sign with the debug keystore (quick, not for Play Store)"))

        print(f"\n{Colors.BOLD}Choose a signing keystore:{Colors.END}")
        for i, (_, label) in enumerate(opts, 1):
            print(f"  {i}. {label}")
        print("  0. Cancel")
        print()
        sel = input(f"{Colors.CYAN}Choice (0-{len(opts)}): {Colors.END}").strip()
        if sel == "0":
            print(f"{Colors.YELLOW}Cancelled.{Colors.END}")
            return False
        if not (sel.isdigit() and 1 <= int(sel) <= len(opts)):
            print(f"{Colors.RED}Invalid choice.{Colors.END}")
            return False
        action = opts[int(sel) - 1][0]

        ks = None  # None ⇒ debug keystore
        if action == "saved":
            ks = {"path": cfg["path"], "store_pass": cfg["store_pass"],
                  "alias": cfg["alias"], "key_pass": cfg["key_pass"]}
        elif action == "create":
            created = self.create_keystore()
            if not created:
                return False
            ks = created
        elif action == "existing":
            print("\nEnter the path to your signing keystore (.jks/.keystore).")
            print("(Press TAB for path autocompletion)")
            ks_in = input(f"{Colors.CYAN}Keystore path: {Colors.END}").strip()
            if not ks_in:
                print(f"{Colors.RED}Keystore path is required.{Colors.END}")
                return False
            ks_path = os.path.abspath(os.path.expanduser(ks_in))
            if not os.path.isfile(ks_path):
                print(f"\n{Colors.RED}Keystore not found: {ks_path}{Colors.END}")
                return False
            store_pass = getpass.getpass("Keystore (store) password: ")
            alias = self.select_alias(ks_path, store_pass)  # lists aliases to pick from
            if not alias:
                return False
            key_pass = getpass.getpass("Key password [Enter = same as store]: ") or store_pass
            ks = {"path": ks_path, "store_pass": store_pass, "alias": alias, "key_pass": key_pass}

        # Offer to remember (incl. a "skip prompts next time / direct build" level).
        self._maybe_remember_release(ks, custom_name)

        return self.run_gradle_task(self._release_task(ks, custom_name))

    def run_on_device(self):
        """Build, install and launch the app — delegates to `studio run`, which auto-adapts
        the project to the Termux toolchain and installs via adb or the package installer.
        Install success is verified against the real package state (works even if Termux is
        backgrounded), and logs can be streamed afterwards over wireless adb."""
        if not self.project_path:
            print(f"{Colors.RED}Please load a project first!{Colors.END}")
            time.sleep(1.5)
            return
        print(f"{Colors.BOLD}Variant:{Colors.END}")
        print(f"  1. {Colors.GREEN}Debug{Colors.END} (default)")
        print("  2. Release")
        print("  0. Cancel")
        v = input(f"{Colors.CYAN}Choice [1]: {Colors.END}").strip() or "1"
        if v == "0":
            return
        if v not in ("1", "2"):
            print(f"{Colors.RED}Invalid choice.{Colors.END}"); time.sleep(1.2); return
        variant = "release" if v == "2" else "debug"
        want_log = input(f"{Colors.CYAN}Stream logcat after launch? (y/N): {Colors.END}").strip().lower() == "y"
        cmd = ["studio", "run", self.project_path]
        if variant == "release":
            cmd.append("--release")
        if want_log:
            cmd.append("--logcat")
        print(f"\n{Colors.YELLOW}Running: {' '.join(cmd)}{Colors.END}\n")
        self.status = "Building, installing & launching..."
        try:
            # Logcat streams until Ctrl-C; let it pass straight through to the terminal.
            rc = subprocess.run(cmd, cwd=self.project_path).returncode
            self.status = "Run complete" if rc == 0 else f"Run failed (exit {rc})"
        except KeyboardInterrupt:
            self.status = "Run stopped"
        except Exception as e:
            print(f"{Colors.RED}Failed: {e}{Colors.END}")
        input("\nPress Enter to continue...")

    def device_and_logs(self):
        """Wireless debugging (Android 11+) and live logcat — no root, no USB cable.
        Once paired, `studio run`/logcat auto-reconnect, giving a true Android-Studio-style
        install → launch → logs flow instead of the fire-and-forget installer hand-off."""
        while True:
            self.print_header()
            print(f"{Colors.BOLD}Device & Logs (Wireless ADB){Colors.END}\n")
            # Show current adb connection state at a glance.
            try:
                devs = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
                connected = [l for l in devs.splitlines() if "\tdevice" in l]
                state = f"{Colors.GREEN}connected: {connected[0].split()[0]}{Colors.END}" if connected \
                        else f"{Colors.YELLOW}not connected{Colors.END}"
            except Exception:
                state = f"{Colors.RED}adb not found{Colors.END}"
            print(f"  ADB status: {state}\n")
            print("1. Pair new device (first-time Wireless debugging setup)")
            print("2. Connect (reconnect a previously paired device)")
            print(f"3. {Colors.GREEN}Logcat{Colors.END} (stream the last-run app's debug logs)")
            print("4. Disconnect")
            print("5. Back to Main Menu")
            print()
            choice = input(f"{Colors.CYAN}Choice (1-5): {Colors.END}").strip()

            if choice == "1":
                subprocess.run(["studio", "adb", "pair"])
                input("\nPress Enter to continue...")
            elif choice == "2":
                subprocess.run(["studio", "adb", "connect"])
                input("\nPress Enter to continue...")
            elif choice == "3":
                self.app_logs()
            elif choice == "4":
                subprocess.run(["studio", "adb", "disconnect"])
                input("\nPress Enter to continue...")
            else:
                return

    # ---------------------------------------------------------- app logs viewer
    #
    # A dedicated, colourised logcat viewer — visually distinct from the plain build-log
    # stream — with per-level highlighting, a header box, and copy/save when you stop it.

    # logcat "threadtime" line: "MM-DD HH:MM:SS.mmm  PID  TID L TAG: message"
    _LOG_RE = None
    _LEVEL_FG = {"V": "\033[90m", "D": "\033[96m", "I": "\033[92m",
                 "W": "\033[93m", "E": "\033[91m", "F": "\033[1;91m", "A": "\033[1;91m"}
    _LEVEL_BG = {"V": "\033[100m", "D": "\033[46m", "I": "\033[42m",
                 "W": "\033[43m", "E": "\033[41m", "F": "\033[41m", "A": "\033[41m"}

    @staticmethod
    def _strip_ansi(s):
        import re
        return re.sub(r"\033\[[0-9;]*m", "", s)

    def _format_log_line(self, line):
        import re
        if self._LOG_RE is None:
            type(self)._LOG_RE = re.compile(
                r"^(\d\d-\d\d )?(\d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEFAS])\s+(.*?):\s?(.*)$")
        # Pass through lines that already carry colour (studio's own status lines).
        if "\033[" in line:
            return line
        m = self._LOG_RE.match(line)
        if not m:
            return f"\033[90m{line}\033[0m"          # separators / non-standard → dim
        _d, t, _pid, _tid, lvl, tag, msg = m.groups()
        fg = self._LEVEL_FG.get(lvl, "\033[0m")
        chip = f"{self._LEVEL_BG.get(lvl, '')}\033[97m {lvl} \033[0m"   # white-on-colour badge
        return f"\033[90m{t}\033[0m {chip} {Colors.BOLD}{tag}\033[0m{fg}: {msg}\033[0m"

    def _log_header_box(self):
        pkg = ""
        try:
            with open(os.path.expanduser("~/.studio/last_pkg")) as f:
                pkg = f.read().strip()
        except Exception:
            pass
        w = 60
        g = Colors.GREEN
        # Pad plain text by length (no wide/emoji chars) so the box borders stay aligned.
        def row(text):
            return f"{g}║{Colors.END}{text[:w]:<{w}}{g}║{Colors.END}"
        print(f"{g}╔{'═' * w}╗{Colors.END}")
        print(row("  APP LOGS  —  logcat (live)"))
        if pkg:
            print(row(f"  package: {pkg}"))
        print(row("  levels:  E error  W warn  I info  D debug  V verbose"))
        print(f"{g}╚{'═' * w}╝{Colors.END}")

    def app_logs(self):
        """Stream the app's logcat in a dedicated, colourised viewer; Ctrl-C to stop and copy/save."""
        import collections
        if not shutil.which("adb"):
            print(f"{Colors.RED}adb not found (pkg install android-tools).{Colors.END}")
            input("\nPress Enter to continue..."); return

        cmd = ["studio", "logcat"]
        if self.project_path:
            cmd.append(self.project_path)

        self.print_header()
        self._log_header_box()
        print(f"{Colors.YELLOW}Streaming… press Ctrl-C to stop and get copy/save options.{Colors.END}\n")

        buf = collections.deque(maxlen=10000)
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            for line in proc.stdout:
                line = line.rstrip("\n")
                buf.append(line)
                print(self._format_log_line(line))
        except KeyboardInterrupt:
            pass
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
        self._logs_post_menu(list(buf))

    def _logs_post_menu(self, lines):
        import re
        # Drop studio's own status/info lines from the copyable set; keep real log lines.
        real = [l for l in lines if self._strip_ansi(l).strip()]
        if not real:
            print(f"\n{Colors.YELLOW}No logs captured (is the app running? try 'Run on Device' first).{Colors.END}")
            input("\nPress Enter to continue..."); return
        errwarn = [l for l in real if re.search(r"\s[WEFA]\s", self._strip_ansi(l))]
        while True:
            print(f"\n{Colors.BOLD}⏸ Logs stopped — {len(real)} lines captured "
                  f"({len(errwarn)} warnings/errors).{Colors.END}")
            print("  1. Copy ALL to clipboard")
            print(f"  2. Copy {Colors.RED}errors + warnings{Colors.END} only to clipboard")
            print("  3. Save to file (Download)")
            print("  4. Resume streaming")
            print("  5. Back")
            c = input(f"{Colors.CYAN}Choice: {Colors.END}").strip()
            if c == "1":
                self._copy_logs(real, "all logs")
            elif c == "2":
                self._copy_logs(errwarn, "errors+warnings")
            elif c == "3":
                self._save_logs(real)
            elif c == "4":
                self.app_logs(); return
            else:
                return

    def _copy_logs(self, lines, what):
        if not lines:
            print(f"{Colors.YELLOW}Nothing to copy.{Colors.END}"); return
        text = "\n".join(self._strip_ansi(l) for l in lines)
        if shutil.which("termux-clipboard-set"):
            try:
                subprocess.run(["termux-clipboard-set"], input=text, text=True)
                print(f"{Colors.GREEN}Copied {len(lines)} lines ({what}) to the clipboard.{Colors.END}")
                return
            except Exception as e:
                print(f"{Colors.RED}Clipboard failed: {e}{Colors.END}")
        print(f"{Colors.YELLOW}termux-clipboard-set unavailable (pkg install termux-api) — saving to file instead.{Colors.END}")
        self._save_logs(lines)

    def _save_logs(self, lines):
        if not lines:
            print(f"{Colors.YELLOW}Nothing to save.{Colors.END}"); return
        fname = "applog_" + time.strftime("%Y%m%d_%H%M%S") + ".txt"
        outdir = next((d for d in ("/storage/emulated/0/Download", "/sdcard/Download")
                       if os.path.isdir(d) and os.access(d, os.W_OK)), os.path.expanduser("~"))
        path = os.path.join(outdir, fname)
        try:
            with open(path, "w") as f:
                f.write("\n".join(self._strip_ansi(l) for l in lines) + "\n")
            print(f"{Colors.GREEN}Saved {len(lines)} lines to {path}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Save failed: {e}{Colors.END}")

    def locate_and_offer_apks(self):
        print(f"\n{Colors.BOLD}{Colors.CYAN}Searching for generated APKs...{Colors.END}")
        apk_pattern = os.path.join(self.project_path, "**/build/outputs/apk/**/*.apk")
        apks = glob.glob(apk_pattern, recursive=True)
        
        if not apks:
            print(f"{Colors.YELLOW}No APKs found. They might have been built to a different location or path.{Colors.END}")
            input("\nPress Enter to continue...")
            return

        print(f"\n{Colors.GREEN}Found APK(s):{Colors.END}")
        for i, apk in enumerate(apks, 1):
            size_mb = os.path.getsize(apk) / (1024 * 1024)
            print(f"{i}. {os.path.basename(apk)} ({size_mb:.2f} MB)")
            print(f"   Path: {apk}")

        print("\nOptions:")
        print(f"1. {Colors.GREEN}Share APK{Colors.END} (Android share sheet — WhatsApp, Drive, Bluetooth…)")
        print("2. Copy APK to Shared Storage (/storage/emulated/0/Download/)")
        print("3. Do nothing (stay in menu)")

        choice = input(f"\n{Colors.CYAN}Choice: {Colors.END}").strip()
        if choice == "1":
            self.share_apk(self._pick_apk(apks))
            input("\nPress Enter to continue...")
        elif choice == "2":
            dest_dir = "/storage/emulated/0/Download"
            if not os.path.exists(dest_dir):
                # Try fallback standard storage path
                dest_dir = "/sdcard/Download"

            if not os.path.exists(dest_dir):
                print(f"{Colors.RED}Could not access shared download directory.{Colors.END}")
                input("\nPress Enter to continue...")
                return

            for apk in apks:
                dest_path = os.path.join(dest_dir, os.path.basename(apk))
                try:
                    shutil.copy2(apk, dest_path)
                    print(f"{Colors.GREEN}Copied successfully to: {dest_path}{Colors.END}")
                except Exception as e:
                    print(f"{Colors.RED}Failed to copy {os.path.basename(apk)}: {e}{Colors.END}")
            input("\nPress Enter to continue...")

    def _pick_apk(self, apks):
        """If there's more than one APK, ask which to act on; otherwise return the only one."""
        if len(apks) == 1:
            return apks[0]
        sel = input(f"{Colors.CYAN}Which APK # (1-{len(apks)}): {Colors.END}").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(apks):
            return apks[int(sel) - 1]
        print(f"{Colors.YELLOW}Defaulting to the first APK.{Colors.END}")
        return apks[0]

    def _ensure_shared(self, apk):
        """Return a path other apps can read. /storage and /sdcard are already shared; a
        Termux-private path (under /data/data/com.termux) is copied into Download, because no
        other app can read Termux's private storage."""
        if apk.startswith("/storage/") or apk.startswith("/sdcard/"):
            return apk
        outdir = next((d for d in ("/storage/emulated/0/Download", "/sdcard/Download")
                       if os.path.isdir(d) and os.access(d, os.W_OK)), None)
        if not outdir:
            print(f"{Colors.YELLOW}No shared storage (run termux-setup-storage) — sharing in place.{Colors.END}")
            return apk
        dst = os.path.join(outdir, os.path.basename(apk))
        try:
            if os.path.abspath(apk) != os.path.abspath(dst):
                shutil.copy2(apk, dst)
            return dst
        except Exception as e:
            print(f"{Colors.RED}Could not copy to shared storage: {e}{Colors.END}")
            return apk

    def share_apk(self, apk):
        """Share the APK as a real file via an ACTION_SEND intent built directly with `am`.

        termux-open wrapped the path in a content://com.termux.files URI that receivers couldn't
        resolve ('Requested file was not found'). Instead we hand the intent a plain file:// URI
        of the APK's actual path (with FLAG_GRANT_READ_URI_PERMISSION), which apps read directly.
        Only Termux-private APKs are first copied to shared Download (others can't read them)."""
        if not apk:
            return
        apk = self._ensure_shared(os.path.abspath(apk))
        if not os.path.isfile(apk):
            print(f"{Colors.RED}APK not found: {apk}{Colors.END}")
            return
        uri = "file://" + apk
        print(f"\n{Colors.YELLOW}Sharing {os.path.basename(apk)} "
              f"({os.path.getsize(apk)/1048576:.2f} MB)…{Colors.END}")
        try:
            res = subprocess.run(
                ["am", "start",
                 "-a", "android.intent.action.SEND",
                 "-t", "application/vnd.android.package-archive",
                 "--eu", "android.intent.extra.STREAM", uri,
                 "--grant-read-uri-permission"],
                capture_output=True, text=True)
            out = (res.stdout + res.stderr).strip()
            if res.returncode != 0 or "Error" in out:
                print(f"{Colors.RED}Share intent error:{Colors.END} {out}")
            else:
                print(f"{Colors.GREEN}Opened the Android share sheet.{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Share failed: {e}{Colors.END}")
        print(f"\n{Colors.CYAN}File location (attach manually if needed):{Colors.END} "
              f"{Colors.BOLD}{apk}{Colors.END}")

    def check_environment(self):
        self.print_header()
        print(f"{Colors.BOLD}Validating Environment Paths:{Colors.END}")
        
        # Verify Java
        try:
            java_ver = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT, text=True)
            print(f"{Colors.GREEN}✔ Java: {java_ver.splitlines()[0]}{Colors.END}")
        except Exception:
            print(f"{Colors.RED}✘ Java is not installed or not in PATH!{Colors.END}")

        # Verify Gradle
        try:
            gradle_ver = subprocess.check_output(["gradle", "-v"], text=True)
            for line in gradle_ver.splitlines():
                if "Gradle " in line:
                    print(f"{Colors.GREEN}✔ {line.strip()}{Colors.END}")
                    break
        except Exception:
            print(f"{Colors.RED}✘ Gradle is not installed or not in PATH!{Colors.END}")

        # Verify SDK
        if os.path.exists(self.android_home):
            print(f"{Colors.GREEN}✔ Android SDK found at: {self.android_home}{Colors.END}")
            # List platforms
            platforms = glob.glob(os.path.join(self.android_home, "platforms/*"))
            if platforms:
                print(f"  Platforms installed: {[os.path.basename(p) for p in platforms]}")
            else:
                print(f"  {Colors.YELLOW}Warning: No platforms installed inside SDK!{Colors.END}")
        else:
            print(f"{Colors.RED}✘ Android SDK directory not found! ({self.android_home}){Colors.END}")

        # Installed JDKs + which one this project builds with (delegates to `studio jdk`).
        print(f"\n{Colors.BOLD}Build JDKs:{Colors.END}")
        try:
            subprocess.run(["studio", "jdk", "list"])
            if self.project_path:
                subprocess.run(["studio", "jdk", "which", self.project_path])
        except Exception as e:
            print(f"{Colors.RED}Could not query JDKs: {e}{Colors.END}")

        print(f"\n{Colors.CYAN}Manage JDKs:{Colors.END}")
        print("  i) Install a JDK (11/17/21)")
        print("  u) Set the build JDK for the loaded project")
        print("  Enter) Back")
        act = input(f"{Colors.CYAN}Choice: {Colors.END}").strip().lower()
        if act == "i":
            ver = input(f"{Colors.CYAN}Version to install (11/17/21): {Colors.END}").strip()
            if ver:
                subprocess.run(["studio", "jdk", "install", ver])
                input("\nPress Enter to continue...")
        elif act == "u":
            if not self.project_path:
                print(f"{Colors.RED}Load a project first.{Colors.END}")
                time.sleep(1.5)
            else:
                ver = input(f"{Colors.CYAN}JDK version for this project (11/17/21): {Colors.END}").strip()
                if ver:
                    subprocess.run(["studio", "jdk", "use", ver, self.project_path])
                    input("\nPress Enter to continue...")
        return

    def menu(self):
        while self.is_running:
            self.print_header()
            print(f"{Colors.BOLD}Main Menu:{Colors.END}")
            print(f"1. {Colors.GREEN}New Project{Colors.END} (Compose or XML template)")
            print(f"2. {Colors.GREEN}Get from VCS{Colors.END} (Clone & import a Git repo)")
            print(f"3. {Colors.GREEN}Load Project{Colors.END} (Set absolute path)")
            print(f"4. {Colors.CYAN}Sync Gradle{Colors.END} (Download dependencies)")
            print(f"5. {Colors.YELLOW}Build Project{Colors.END} (Compile APK / Run on device ▶)")
            print(f"6. {Colors.GREEN}Device & Logs{Colors.END} (Wireless ADB + Logcat)")
            print(f"7. {Colors.HEADER}Run Custom Gradle Command{Colors.END}")
            print(f"8. Check Environment Setup")
            print(f"9. Exit")
            print()

            choice = input(f"{Colors.CYAN}Select an option (1-9): {Colors.END}").strip()

            if choice == "1":
                self.create_new_project()
            elif choice == "2":
                self.clone_from_vcs()
            elif choice == "3":
                self.load_project()
            elif choice == "4":
                self.sync_project()
            elif choice == "5":
                self.build_project()
            elif choice == "6":
                self.device_and_logs()
            elif choice == "7":
                self.run_custom_gradle_command()
            elif choice == "8":
                self.check_environment()
            elif choice == "9":
                self.is_running = False
                print(f"\n{Colors.BOLD}Goodbye from Termux Studio!{Colors.END}")
            else:
                print(f"{Colors.RED}Invalid option!{Colors.END}")
                time.sleep(1)

if __name__ == "__main__":
    studio = TermuxStudio()
    # If a project path is passed as a command-line argument, open it; otherwise auto-reopen
    # the last project from the previous session so `studio start` lands ready to build.
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        studio.open_project(sys.argv[1], status="Project Loaded via CLI")
    else:
        last = TermuxStudio.last_project()
        if last:
            studio.open_project(last, status="Reopened last project")
    studio.menu()
