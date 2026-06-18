# Building the Shreeji Admin Desktop App

These steps are for Prince to package the admin desktop app on a Windows machine.

## Prerequisites

Install these first:

- Python 3.12
- pip
- A git clone of this repository on the Windows machine

Open PowerShell or Command Prompt in the project root before running the commands below.

## Install Dependencies

Install the normal app dependencies and the desktop packaging dependencies:

```powershell
pip install -r requirements.txt -r requirements_desktop.txt
```

## Create the Environment File

Create a `.env` file in the project root.

It must include:

```env
DATABASE_URL=your_neon_database_url_here
SECRET_KEY=your_secret_key_here
```

`DATABASE_URL` should be the raw Neon PostgreSQL URL. Do not wrap it in quotes.

## Verify in Dev Mode

Run the desktop app before building the `.exe`:

```powershell
python desktop_app.py
```

The admin window should open. Confirm the app loads correctly and can connect to Neon.

## Build the EXE

From the project root, run:

```powershell
pyinstaller ShreejiAdmin.spec --clean
```

## Output Location

After the build finishes, the executable will be here:

```text
dist/ShreejiAdmin/ShreejiAdmin.exe
```

## Post-Build Step

Copy the `.env` file into this folder:

```text
dist/ShreejiAdmin/
```

The `.env` file must sit alongside `ShreejiAdmin.exe` because the app reads it at runtime.

## Giving It to the Client

Zip the entire folder:

```text
dist/ShreejiAdmin/
```

Send that zip file to the client. They should extract the zip and double-click:

```text
ShreejiAdmin.exe
```

## Internet Requirement

The desktop app requires internet access to connect to the Neon database. It will not work fully offline.

## Updates

There is no auto-update mechanism yet. To update the desktop app, rebuild it and send the client a new zip of the full `dist/ShreejiAdmin/` folder.
