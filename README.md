# 🤖 Zero-Cost AI Calling Agent

A real-time, cloud-hosted AI voice assistant that answers incoming phone calls, conducts natural conversations, and automatically generates summaries. 

Built with **FastAPI**, **Groq (LLM)**, and **Deepgram (STT/TTS)**, and designed for 24/7 availability on **Render**.

## ✨ Features
- **Real-Time Voice Interaction**: Ultra-low latency conversation using WebSockets.
- **Smart Transcription**: High-accuracy Speech-to-Text via Deepgram Nova-2.
- **Fast Reasoning**: Instant AI responses powered by Groq's Llama 3 models.
- **Automated Summaries**: Receives full call logs and summaries via Webhooks after each call.
- **Cloud Native**: Ready for deployment on Render with Docker support.

## 🛠️ Tech Stack
- **Backend**: Python, FastAPI
- **Voice Engine**: Deepgram (STT & TTS)
- **Intelligence**: Groq (Llama 3-70B)
- **Telephony**: Twilio (Media Streams)
- **Hosting**: Render (Cloud Web Service)

## 🚀 Quick Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/ANIRUDH1817/CALL_AGENT.git
   cd CALL_AGENT
