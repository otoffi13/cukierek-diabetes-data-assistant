## Requirements

To run the project locally, you need:

- Python 3.10+
- virtual environment, for example `venv`
- installed Python dependencies from `requirements.txt`
- configured environment variables in a local `.env` file
- running Ollama instance for local LLM-based features
- email account credentials for email notification/sending features

## Environment variables

The project uses environment variables stored in a local `.env` file.

Create a `.env` file in the root directory of the project:

```text
cukierek-diabetes-data-assistant/
│
├── .env
├── README.md
├── requirements.txt
└── ...
```

Example `.env` file:

```env
# Email configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com

# Ollama configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

# Application settings
APP_ENV=development
```

Do not commit the `.env` file to GitHub.

Only an example file such as `.env.example` should be stored in the repository.

## Email configuration

The project can use an email account to send notifications or reports.

For Gmail, it is recommended to use an **App Password** instead of the main account password.

Required variables:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
```

The real password is stored only locally in the `.env` file and should never be committed to the repository.

## Ollama configuration

Some features of the project use a local language model through Ollama.

Before running the project, make sure that Ollama is installed and running locally.

Example model setup:

```bash
ollama pull llama3.1
```

The application expects Ollama to be available at:

```text
http://localhost:11434
```

You can configure this using:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

If you use a different model, change the `OLLAMA_MODEL` value in your `.env` file.

## Installation

Clone the repository:

```bash
git clone https://github.com/otoffi13/cukierek-diabetes-data-assistant.git
cd cukierek-diabetes-data-assistant
```

Create and activate a virtual environment:

```bash
python -m venv venv
```

On Windows:

```bash
venv\Scripts\activate
```

On Linux/macOS:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the local `.env` file based on `.env.example`:

```bash
copy .env.example .env
```

Then fill in your local email and Ollama configuration.

## Running the project

After installing dependencies and configuring the `.env` file, run the main application file:

```bash
python main.py
```

If the project uses a different entry point, run the appropriate script from the project directory.

## Security note

This repository must not contain:

- real medical data,
- exported ZIP files from diabetes platforms,
- private CGM, insulin or carbohydrate records,
- `.env` files,
- email passwords,
- API keys,
- local database files with private data.

Sensitive files should be excluded using `.gitignore`.
