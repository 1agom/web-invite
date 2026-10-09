# Web Invite

A local-first invitation image personalizer. Upload a PSD template, map editable text fields, preview changes in the browser, and export PNG images. The browser renders text with Canvas; the local Python service stores templates and exported files.

This project is a multi-field personalization tool. It is not a general-purpose Photoshop Action runner or a pixel-identical PSD renderer.

## Features

- PSD text-layer inspection and editable-field suggestions
- Browser Canvas preview with uploaded fonts
- Text, fill-in, and mutually exclusive choice fields
- Per-version underline toggle for fill-in fields
- CSV, TSV, and XLSX list import with column mapping and preview
- Export preflight checks, batch version gallery, and PNG export
- Mobile preview, form, list, and version views
- Local template backup and restore
- Optional static-site packaging for read-only visitor use

## Requirements

- Python 3.10 or newer
- Node-free runtime; the XLSX browser library is vendored under `vendor/` with its Apache-2.0 license
- Dependencies listed in `requirements.txt`
- A PSD template and fonts that you are permitted to use and redistribute within your deployment

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Set secrets in the current shell. Use your own strong values; never commit them:

   ```powershell
   $env:INVITE_ADMIN_KEY = "your-long-random-admin-key"
   $env:INVITE_PAGE_PASSWORD = "your-private-page-password"
   ```

4. Start the local service:

   ```powershell
   python server.py
   ```

5. Open `http://127.0.0.1:8790` and upload a PSD template and a licensed font file.

The server refuses to start if either secret is unset. For other shells, set the equivalent environment variables before launching Python.

## Templates and Assets

Templates and fonts are runtime user data and are intentionally not included in this repository. Upload them through the local UI. The service stores them under `assets/templates/` and `assets/fonts/`; generated PNG files go to `output/`, and event logs go to `logs/`.

Do not publish real invitation designs, attendee names, exports, visitor logs, API keys, passwords, or fonts without explicit redistribution rights. `.gitignore` excludes the usual local-data directories, but review `git status` and the staged file list before every commit.

## Static Visitor Site

`tools/build_site.py` packages the current local templates for static hosting. The generated package contains invitation artwork and fonts, so treat it as publishable user content: inspect the templates and confirm all image/font rights before hosting. Static mode renders and exports in the visitor's browser and does not provide server-side export statistics, template administration, or backup/restore.

## Rendering Limits

The PSD parser extracts text-layer metadata and builds a flattened background with editable text redrawn by Canvas. Basic position, font, size, color, alignment, spacing, fill fields, and choices are supported. Arbitrary Photoshop layer effects, masks, blend modes, smart objects, warped text, mixed per-character formatting, and general Photoshop Actions are not guaranteed to render identically. Flatten complex decorative artwork before using it as a template background, then verify each template with sample exports.

## Security and Privacy

- List files are parsed in the browser; the application does not upload list contents to the server.
- The local server writes generated PNG files and logs visitor IP, user-agent, template, and filenames when used in a shared deployment. Review retention and access controls before exposing the service publicly.
- Use HTTPS and a strong random `INVITE_ADMIN_KEY` for any shared deployment.
- Never put real credentials in `.env.example`, source files, screenshots, fixtures, or public issue reports.

## License

The project source is offered under the MIT License. Third-party libraries, fonts, PSDs, images, and templates retain their own licenses; this repository license does not grant rights to those assets.
