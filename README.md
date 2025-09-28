# 🌐 Web Scraping App with libpostal & FastAPI

This project is a **FastAPI-based web scraping application** that leverages the powerful [libpostal](https://github.com/openvenues/libpostal) library for parsing and normalizing international postal addresses. Built inside a Docker container for portability and ease of deployment, this app allows you to scrape address-related data from web sources and process them using robust geoparsing capabilities.

Ideal for developers, data engineers, or researchers needing structured address data extraction at scale.

---

## 🚀 Features

- ✅ Dockerized environment with Ubuntu 22.04 base
- ✅ Pre-installed `libpostal` C library + Python bindings
- ✅ FastAPI backend with auto-reload for development
- ✅ Uvicorn ASGI server
- ✅ Modular structure: `scrapping.py` for scraping logic, `main.py` for API endpoints
- ✅ Template support (for future frontend rendering)
- ✅ Easy configuration via `.env` file

---

## 🐳 Prerequisites

### 1. Install Docker

If you don’t have Docker installed, follow the official guide for your OS:

👉 [Install Docker Engine](https://docs.docker.com/engine/install/)

Verify installation:

```
docker --version
```

---

## ⚙️ Setup Instructions

### Step 1: Clone the Repository

```
git clone <your-repo-url>
cd <your-project-directory>
```

### Step 2: Create `.env` Configuration File

Create a `.env` file in your **project root directory** (same level as `Dockerfile`). If your application expects it elsewhere (e.g., home directory), adjust volume mounts accordingly.  
💡 **Tip:** Rename `sample_env` (if provided) to `.env` and fill in your values.

**Sample `.env` file:**

### Required API credentials and config

```
MY_KEY=Your Scrapping dog key
GEO_MAP_API= openWeatherMap api key
```

📌 **Important:** Replace placeholder values with your actual credentials or config.

---

### Step 3: Build the Docker Image

From your project directory (where `Dockerfile` is located):

```
docker build -t web-scraper-app .
```

This will:

- Install system dependencies
- Clone, configure, and compile `libpostal`
- Install Python packages from `requirements.txt`
- Copy your app files (`main.py`, `scrapping.py`, `templates/`, etc.)

⏱️ **Note:** Building libpostal may take 5–15 minutes depending on your machine.

---

### Step 4: Run the Container

**Standard Run (.env in project root):**

```
docker run -p 8000:8000
--env-file .env
-v $(pwd)/templates:/app/templates
--name scraper-container
web-scraper-app



```

**If `.env` is in your home directory:**

```
docker run -p 8000:8000
--env-file ~/.env
-v $(pwd)/templates:/app/templates
--name scraper-container
web-scraper-app
```

🔧 You can also pass individual environment variables with `-e API_KEY=xxx`.

---

### 🌍 Access the App

Once running, open your browser and go to:  
👉 [http://localhost:8000](http://localhost:8000/)

For interactive API documentation (Swagger UI):  
👉 [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📁 Project Structure

```
.
├── Dockerfile
├── requirements.txt
├── main.py # FastAPI app entrypoint
├── scrapping.py # Web scraping logic
├── templates/ # HTML/Jinja2 templates (optional)
├── sample_env # Sample env file — rename to .env
└── README.md # You are here!
```

---

## 🛠️ Customization Tips

- Modify `scrapping.py` to change scraping targets or parsing logic.
- Add new routes/endpoints in `main.py`.
- Extend `requirements.txt` for additional Python packages (e.g., `beautifulsoup4`, `requests`, `python-dotenv`).
- Adjust `./configure` flags in Dockerfile if you need to disable SSE2 or use Senzing models:
  ```
  # RUN ./configure --datadir=/usr/local/share/libpostal --disable-sse2
  ```

---
