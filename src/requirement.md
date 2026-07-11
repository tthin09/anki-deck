# Introduction
I want to build a script for my non-tech friend to use and it will auto generate a deck from .txt and add to their Anki. I want this script to be setup so that when they run, they don't have to setup any environment to do it.

From the word they want to learn in English, I want to call a free LLM API for them to generate the word description and deck for me. The system prompt is the file agent-prompt.md

# Requirement
The .txt file will be in folder /input (with any name). It will call a free public LLM API to generate the word description, then we will resolve that to an anki deck, and add it to the user Anki deck. Create a plan to do it for me