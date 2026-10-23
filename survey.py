import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Setup constants and configuration
TIMEOUT = 60
LOGIN_URL = "https://sipad.tums.ac.ir/Dashboard"
PWA_NEVER_SHOW_KEY = "pwa_never_show_forever"
PWA_PROMPT_TIMEOUT = 5
DRIVER_DOWNLOAD_TIMEOUT = 30
HUAWEI_CHROMEDRIVER_INDEX = "https://repo.huaweicloud.com/chromedriver/"
CHROMEDRIVER_CACHE_DIRECTORY = "chromedriver_cache"

CHROMEDRIVER_MIRROR_TEMPLATES = {
    "modern": (
        (
            "Huawei Cloud",
            "https://repo.huaweicloud.com/chromedriver/"
            "{version}/chromedriver-win64.zip",
        ),
        (
            "npmmirror Chrome for Testing",
            "https://registry.npmmirror.com/-/binary/chrome-for-testing/"
            "{version}/win64/chromedriver-win64.zip",
        ),
        (
            "npmmirror Chrome for Testing CDN",
            "https://cdn.npmmirror.com/binaries/chrome-for-testing/"
            "{version}/win64/chromedriver-win64.zip",
        ),
    ),
    "legacy": (
        (
            "npmmirror ChromeDriver",
            "https://registry.npmmirror.com/-/binary/chromedriver/"
            "{version}/chromedriver_win32.zip",
        ),
        (
            "npmmirror ChromeDriver CDN",
            "https://cdn.npmmirror.com/binaries/chromedriver/"
            "{version}/chromedriver_win32.zip",
        ),
    ),
}
CHROME_VERSION_PATTERN = re.compile(
    r"(?<!\d)\d+\.\d+\.\d+\.\d+(?!\d)"
)

def find_installed_chrome():
    """Find an existing Chrome installation without provisioning a browser."""
    roots = (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMW6432"),
        os.environ.get("LOCALAPPDATA"),
    )
    relative_path = Path("Google") / "Chrome" / "Application" / "chrome.exe"
    candidates = [
        Path(root) / relative_path
        for root in roots
        if root
    ]
    candidates.extend(
        Path(path)
        for path in (
            shutil.which("chrome.exe"),
            shutil.which("chrome"),
        )
        if path
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError(
        "Google Chrome was not found. Install Chrome manually; "
        "this program will not download a browser."
    )

def find_local_chromedriver():
    """Find a side-by-side local driver without downloading one."""
    application_directory = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    candidates = []

    # Support running survey.py or a side-by-side executable distribution.
    candidates.extend(
        (
            application_directory / "chromedriver.exe",
            Path.cwd() / "chromedriver.exe",
        )
    )

    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if str(candidate).lower() in seen:
            continue
        seen.add(str(candidate).lower())
        if candidate.is_file():
            return str(candidate)

    return None


def _open_mirror_url(url):
    request = Request(
        url,
        headers={"User-Agent": "SipadSurvey ChromeDriver bootstrap"},
    )
    return urlopen(request, timeout=DRIVER_DOWNLOAD_TIMEOUT)


def _get_installed_chrome_version(chrome_path):
    """Read the full Chrome version from the installed executable."""
    chrome_path = str(chrome_path)
    version_output = ""

    if os.name == "nt":
        escaped_path = chrome_path.replace("'", "''")
        powershell_command = (
            f"(Get-Item -LiteralPath '{escaped_path}')."
            "VersionInfo.ProductVersion"
        )
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if powershell:
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    powershell_command,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            version_output = result.stdout

    if not version_output:
        result = subprocess.run(
            [chrome_path, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        version_output = f"{result.stdout}\n{result.stderr}"

    match = CHROME_VERSION_PATTERN.search(version_output)
    if not match:
        raise RuntimeError(
            "Could not determine the installed Google Chrome version. "
            "Install Chrome manually or place a compatible chromedriver.exe "
            "beside the application."
        )

    return match.group(0)


def _version_key(version):
    return tuple(int(part) for part in version.split("."))


def _read_huawei_versions_for_build(build_version):
    """Find available ChromeDriver patch versions on Huawei Cloud."""
    try:
        with _open_mirror_url(HUAWEI_CHROMEDRIVER_INDEX) as response:
            index_html = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError):
        return []

    versions = set(
        re.findall(
            rf'href="({re.escape(build_version)}\.\d+)/"',
            index_html,
        )
    )
    return sorted(versions, key=_version_key, reverse=True)


def _read_npmmirror_release_version(build_version):
    """Find the matching legacy driver version on npmmirror."""
    release_urls = (
        "https://registry.npmmirror.com/-/binary/chromedriver/"
        f"LATEST_RELEASE_{build_version}",
        "https://cdn.npmmirror.com/binaries/chromedriver/"
        f"LATEST_RELEASE_{build_version}",
    )
    for url in release_urls:
        try:
            with _open_mirror_url(url) as response:
                version = response.read().decode("ascii", errors="ignore").strip()
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
            return version
    return None


def _driver_version_candidates(chrome_version):
    """Yield exact and mirror-available compatible driver versions."""
    parts = chrome_version.split(".")
    build_version = ".".join(parts[:3])
    candidates = [chrome_version]
    major_version = int(parts[0])

    if major_version >= 115:
        candidates.extend(_read_huawei_versions_for_build(build_version))
    else:
        legacy_version = _read_npmmirror_release_version(build_version)
        if legacy_version:
            candidates.append(legacy_version)

    seen = set()
    for version in candidates:
        if version not in seen:
            seen.add(version)
            yield version


def _driver_cache_root():
    """Keep downloaded drivers beside the script or packaged executable."""
    application_directory = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return application_directory / CHROMEDRIVER_CACHE_DIRECTORY


def _find_cached_chromedriver(chrome_version):
    """Find a previously mirror-downloaded driver for this Chrome build."""
    cache_root = _driver_cache_root()
    if not cache_root.is_dir():
        return None

    build_prefix = ".".join(chrome_version.split(".")[:3]) + "."
    cached_drivers = []
    for version_directory in cache_root.iterdir():
        if not version_directory.is_dir():
            continue
        if not version_directory.name.startswith(build_prefix):
            continue
        try:
            version_key = _version_key(version_directory.name)
        except ValueError:
            continue
        driver_path = version_directory / "chromedriver.exe"
        if driver_path.is_file():
            cached_drivers.append((version_key, driver_path))

    if not cached_drivers:
        return None
    return str(max(cached_drivers, key=lambda item: item[0])[1])


def _download_and_extract_chromedriver(url, version):
    """Download a mirror archive and cache its chromedriver.exe."""
    cache_directory = _driver_cache_root() / version
    target_path = cache_directory / "chromedriver.exe"
    if target_path.is_file():
        return str(target_path)

    with tempfile.TemporaryDirectory(prefix="sipad-chromedriver-") as temp_dir:
        archive_path = Path(temp_dir) / "chromedriver.zip"
        with _open_mirror_url(url) as response, archive_path.open("wb") as archive:
            shutil.copyfileobj(response, archive)

        try:
            with zipfile.ZipFile(archive_path) as archive:
                driver_members = [
                    member
                    for member in archive.namelist()
                    if Path(member).name.lower() == "chromedriver.exe"
                ]
                if not driver_members:
                    raise RuntimeError(
                        "The mirror archive does not contain chromedriver.exe."
                    )
                driver_member = driver_members[0]
                extracted_path = Path(temp_dir) / "chromedriver.exe"
                with (
                    archive.open(driver_member) as source,
                    extracted_path.open("wb") as destination,
                ):
                    shutil.copyfileobj(source, destination)
        except (zipfile.BadZipFile, KeyError) as error:
            raise RuntimeError("The mirror returned an invalid driver archive.") from error

        cache_directory.mkdir(parents=True, exist_ok=True)
        temporary_target = cache_directory / "chromedriver.exe.download"
        shutil.copyfile(extracted_path, temporary_target)
        os.replace(temporary_target, target_path)

    return str(target_path)


def find_or_download_chromedriver(chrome_path):
    """Use a local driver first, then download one from an Iran-accessible mirror."""
    local_driver = find_local_chromedriver()
    if local_driver:
        return local_driver

    chrome_version = _get_installed_chrome_version(chrome_path)
    cached_driver = _find_cached_chromedriver(chrome_version)
    if cached_driver:
        print(f"Using cached ChromeDriver for Chrome {chrome_version}.")
        return cached_driver

    print(
        "Local ChromeDriver was not found. "
        "Attempting to download a compatible driver from a mirror..."
    )
    mirror_type = "modern" if int(chrome_version.split(".", 1)[0]) >= 115 else "legacy"
    errors = []
    for version in _driver_version_candidates(chrome_version):
        for mirror_name, url_template in CHROMEDRIVER_MIRROR_TEMPLATES[mirror_type]:
            url = url_template.format(version=version)
            try:
                driver_path = _download_and_extract_chromedriver(url, version)
            except Exception as error:
                errors.append(f"{mirror_name}: {error}")
                continue
            print(f"Downloaded ChromeDriver from {mirror_name}.")
            return driver_path

    details = "; ".join(errors[-4:])
    raise RuntimeError(
        "ChromeDriver was not found locally and mirror download failed. "
        "Check your internet connection or place chromedriver.exe beside the "
        f"application. Details: {details}"
    )

# Input credentials and preferences
username = input("Enter your username: ")
password = input("Enter your password: ")
print("Please select the corresponding number to indicate your preferred option:\n"
      "0: very good\n1: good\n2: average\n3: weak\n4: very weak\n5: undecided\n(Default Response: 0)")
try:
    opt = int(input("Enter the corresponding number: "))
    if opt not in range(6):
        opt = 0
except ValueError:
    opt = 0

print("The initial startup process may require some time.")

# Initialize the WebDriver
# Use only the installed browser. Prefer a side-by-side local ChromeDriver and
# download a driver from a mirror only when no local copy is available.
os.environ["SE_AVOID_BROWSER_DOWNLOAD"] = "true"
chrome_options = Options()
chrome_path = find_installed_chrome()
chrome_options.binary_location = chrome_path
service = Service(find_or_download_chromedriver(chrome_path))
driver = webdriver.Chrome(service=service, options=chrome_options)
wait = WebDriverWait(driver, TIMEOUT)

def suppress_pwa_prompt():
    """Prevent Sipad's PWA install dialog from blocking the automation flow."""
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": (
                f"try {{ localStorage.setItem({PWA_NEVER_SHOW_KEY!r}, 'true'); }}"
                " catch (_) {}"
            )
        },
    )

def dismiss_pwa_prompt(timeout=PWA_PROMPT_TIMEOUT):
    """Close the PWA dialog if the website renders it despite the guard."""
    driver.switch_to.default_content()

    def find_dismiss_button(current_driver):
        selectors = (
            ".custom-install-modal .cancel-btn",
            ".custom-install-modal .never-show-btn",
        )
        for selector in selectors:
            for button in current_driver.find_elements(By.CSS_SELECTOR, selector):
                if button.is_displayed() and button.is_enabled():
                    return button
        return False

    try:
        button = WebDriverWait(
            driver, timeout, poll_frequency=0.2
        ).until(find_dismiss_button)
    except TimeoutException:
        return False

    try:
        button.click()
    except Exception:
        driver.execute_script("arguments[0].click();", button)
    return True

def switch_to_frame(locator, by=By.XPATH):
    """Switch to an iframe identified by a Selenium locator."""
    iframe = wait.until(EC.presence_of_element_located((by, locator)))
    driver.switch_to.frame(iframe)

def click_element(locator, by=By.XPATH):
    """Wait and click an element identified by a Selenium locator."""
    element = wait.until(EC.element_to_be_clickable((by, locator)))
    element.click()

def fill_field(locator, value, by=By.XPATH):
    """Wait for a field and fill it with a value."""
    field = wait.until(EC.presence_of_element_located((by, locator)))
    field.clear()
    field.send_keys(value)
    return field

# Open the website and login
suppress_pwa_prompt()
driver.get(LOGIN_URL)
dismiss_pwa_prompt()

# The public dashboard now renders the login entry as a dashboard tile. Clicking
# it creates the login iframe asynchronously, so do not rely on the old
# hard-coded iframe index or absolute Angular XPath.
click_element(
    "mat-grid-tile .recomand[role='button']",
    By.CSS_SELECTOR,
)
driver.switch_to.default_content()
switch_to_frame(
    "iframe[id^='iframe_'][src*='route=singin'], "
    "iframe[id^='iframe_'][src*='route=signin']",
    By.CSS_SELECTOR,
)

# Fill in login credentials
fill_field("input[name='username']", username, By.CSS_SELECTOR)
password_field = fill_field("input[name='password']", password, By.CSS_SELECTOR)
password_field.send_keys(Keys.RETURN)

# Navigate to survey
driver.switch_to.default_content()
switch_to_frame("iframe_-1", By.ID)
click_element("/html/body/form/div[5]/div/div/table/tbody/tr/td[7]/input")
driver.switch_to.default_content()
switch_to_frame("iframe_New_EvalAnswerSubject1_Tab", By.ID)

# Process survey responses
all_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, "/html/body/form/div[5]/div/div/table/tbody/*")))

for _ in range(len(all_elements)):
    while True:
        try:
            driver.switch_to.default_content()
            switch_to_frame("iframe_New_EvalAnswerSubject1_Tab", By.ID)
            click_element("/html/body/form/div[5]/div/div/table/tbody/tr[1]/td[12]/input")
            driver.switch_to.default_content()
            switch_to_frame("iframe_New_EvalAnswerListItem_Tab", By.ID)
            
            elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, f"//input[starts-with(@id, 'rb{opt}')]")))
            for element in elements:
                element.click()
            
            click_element("/html/body/form/div[3]/input")
            break
        except Exception:
            pass

# Close the browser
driver.quit()
print("Enjoy!")
