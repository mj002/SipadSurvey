# SipadSurvey

Automate Sipad survey responses using Google Chrome.

## Run the Windows executable

The ready-to-run executable is **[dist/survey.exe](dist/survey.exe)**. Python is not required for this version.

1. Install Google Chrome if it is not already installed.
2. Download and run `survey.exe` from the `dist` folder.
3. Follow the prompts to enter your credentials and preferred response.

You can minimize the application and continue using your device while it runs.

## Run from source

With Python and Google Chrome installed, run:

```sh
pip install selenium==4.27.1
python survey.py
```

## ChromeDriver and cache

The app uses your installed Chrome; it never downloads the browser.

The current version stores its driver cache in the `chromedriver_cache` folder beside `survey.exe`. If you used an earlier version, you can free up disk space by deleting the old cache at `%LOCALAPPDATA%\SipadSurvey\chromedriver` after closing any older versions of the app.
