# Novel Downloader Web Application

A modular, production-grade Python downloader pipeline for `fictionzone.net` novels with an interactive FastAPI-powered HTML5/CSS3/JS dashboard.

## Features

- **Modular Architecture**: Separate backend clients, filesystem cache management, page scraping workers, and EPUB builders.
- **Vibrant Glassmorphic UI**: High-fidelity dark mode with smooth CSS animations, dynamic range limits, and live logging.
- **Intelligent EPUB Builder**: Canonical chapter list mapping, indexing sorting, and chapter-id-level deduplication to prevent wrong ordering or double chapters.
- **Automatic Caching**: Skip downloading cached chapter text files to reduce bandwidth and API rate limits.
- **Interactive Range Selector**: Limit downloads from chapter X to Y instead of pulling the entire novel.
- **Token Pause & Resume**: Prompts the user with an overlay card when hits 401 Unauthorized, pausing the scraper, and resuming immediately upon pasting a new JWT token.

## Setup Instructions

1. **Install Dependencies**:
   Open a terminal and install the required libraries:
   ```bash
   pip install -r requirements.txt
   ```

2. **Launch the FastAPI Server**:
   Run the entry point script:
   ```bash
   python main.py
   ```

3. **Access the Dashboard**:
   Open your browser and navigate to:
   ```
   http://127.0.0.1:8000
   ```

4. **Scraping a Novel**:
   - Paste the landing page URL of a novel from `fictionzone.net`.
   - Copy the `authorization` Bearer token header from Chrome DevTools (Network tab -> click any gateway API request) and paste it into the token input.
   - Click **Verify** to validate the token.
   - Click **Analyze Novel** to pull metadata and populate the range selectors.
   - Adjust the chapter ranges or toggle checkboxes.
   - Click **Start Downloader** to track the live log console and progress bar.
   - Download the compiled EPUB from the shelf!
