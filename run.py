import os
from app import create_app

# Load the environment name to boot the appropriate configuration
env = os.environ.get("FLASK_ENV", "development")
app = create_app(env)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Run the application locally
    app.run(host="0.0.0.0", port=port)
