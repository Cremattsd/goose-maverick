RealNex AI Chatbot 🚀
Welcome to the RealNex AI Chatbot, a cutting-edge, sci-fi-inspired interface that makes interacting with RealNex a thrilling experience! With two powerful personalities—Maverick for Q&A and Goose for data import preparation—this chatbot combines futuristic design with seamless functionality. Featuring neon gradients, glowing animations, and a cyberpunk aesthetic, it’s not just a tool—it’s an adventure.
Features 🌌

Futuristic UI: Neon gradients, glowing effects, and smooth animations for an immersive experience.
Maverick Personality: Answers RealNex questions using a knowledge base, with fallback to xAI for general insights.
Goose Personality: Extracts data from files (images, PDFs, spreadsheets), maps it to RealNex CRM fields using the V1 API, and prepares it for manual import, with a snapshot of the mapped data.
CRM Token Security: Data processing requires a RealNex CRM token; without one, users can only ask questions. Token persists in localStorage for convenience, with a "Clear Token" option.
Drag-and-Drop Uploads: Upload files with a pulsating drop zone, plus camera and photo library support.
Cyberpunk Gauges: Track upload and normalization progress with neon-styled gauges.
Responsive Design: Optimized for all devices with a sleek, modern layout.

Setup on Render 🛠️

Create a GitHub Repository:
Create a new repository named realnex-chatbot.
Upload all files as outlined in the directory structure below.


Deploy to Render:
Go to Render and create a new Web Service.
Connect your GitHub repository (realnex-chatbot).
Render will detect render.yaml. Set the environment variable:
XAI_API_KEY: Your xAI API key.


Deploy the service.


Access the Chatbot:
Navigate to https://your-app-name.onrender.com/static/index.html.
Start chatting with Maverick or prepare data with Goose (CRM token required).



Directory Structure 📁

static/: Frontend assets
index.html: Main UI with futuristic design
maverick-icon.png: Icon for Maverick
goose-icon.png: Icon for Goose


app.py: FastAPI backend
knowledge_base.json: Q&A for Maverick
install_tesseract.sh: Script to install Tesseract on Render
render.yaml: Render deployment config
requirements.txt: Python dependencies
.gitignore: Files to ignore in Git
README.md: Project documentation

Usage 🌠

Access the chatbot at your Render URL (/static/index.html).
Select Maverick to ask RealNex questions (no token needed).
Select Goose to process data for import (requires a RealNex CRM token). Goose will extract and map data, which you can then manually import into RealNex CRM.
Enjoy the snapshots of mapped data in the chat.

Screenshots ✨
Coming soon: Screenshots of the neon-lit, sci-fi interface!
Contributing 🤝
Feel free to fork this repository, submit pull requests, or open issues to enhance this galactic chatbot experience!
