from curses import wrapper
import curses
import openai
import os
import queue
import threading
import time
import textwrap

openai.api_key = os.environ.get('OPENAI_API_KEY')

client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def get_response(prompt):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

def generate_next_section(instruction):
    document = ''
    with open("DOCUMENT.txt", "r") as file:
        document = file.read()

    prompt = f"""
    You are an AI agent that helps write articles for a blog.
    CURRENT_DOCUMENT: {document}
    GOALS_FOR_ARTICLE: {instruction}
    GOALS_FOR_SECTION:
    - Write the next section of the article.
    - The section should should be between 100 words
    - The section should follow logically previous section.
    - If the only content in the document is the title, write an introduction section.
    - If the article is near the word count limit, write a conclusion.
    - If the section is a conclusion, at the end of the section, include
      the statement "END_ARTICLE" at the end of the section.
    """

    end_article = False
    try:
      response = get_response(prompt)
      with open("DOCUMENT.txt", "a") as file:
          file.write(response)

      if "END_ARTICLE" in response:
          end_article = True

      summary_prompt = f"""
      Summarize this section {response} in a short sentence.
      The summary should be 30 characters or less.
      """
      summary = get_response(summary_prompt)
      summary = summary
    except Exception as e:
      summary = f"An error occurred: {e}"

    return {
        "section": response,
        "summary": summary,
        "end_article": end_article
    }


def chatbot(message_queue, shared_data):
    count = 0
    while True:
        if shared_data.get('prompt'):
            message = get_response(f"""
              You are an AI agent that helps write articles for a blog.
              Respond to the {shared_data['prompt']} with a short sentence
              no more than 30 characters telling the user they will include
              the information in the article.
            """)
            shared_data['instruction'] = shared_data['instruction'] + shared_data['prompt']
            shared_data['prompt'] = None
            message_queue.put((f"Agent: {message}", 'chatbot'))

        if shared_data.get('running', True):
            message_queue.put((f"Agent: Writing the next section of the document.", 'chatbot'))
            summary_object = generate_next_section(shared_data['instruction'])
            summary_text = summary_object['summary']
            message_queue.put((f"Agent: {summary_text}", 'chatbot'))
            if summary_object['end_article']:
                message_queue.put(("Agent: The article is complete.", 'chatbot'))
                break
            time.sleep(1)


def input_loop(stdscr, message_queue, chat_win, input_win, shared_data):
    curses.curs_set(1) # Make the cursor visible.
    input_win.keypad(True) # Enable keypad mode.
    shared_data['input_text'] = ''
    shared_data['running'] = False # Chatbot is running by default.

    while True:
        input_win.clear()
        input_win.addstr("> " + shared_data['input_text'])
        input_win.refresh()

        c = input_win.getch()
        if c == 10: # Enter key.
            input_text = shared_data['input_text'].lower()
            if input_text == 'exit':
                message_queue.put(('exit', 'system'))
                break
            elif input_text == 'pause':
                shared_data['running'] = False
                message_queue.put(("You: Paused chatbot.", 'user'))
            elif input_text == 'start':
                shared_data['running'] = True
                message_queue.put(("You: Started chatbot.", 'user'))
            else:
                message_queue.put((f"You: {shared_data['input_text']}", 'user'))
                shared_data['prompt'] = str(shared_data['input_text'])
            shared_data['input_text'] = ''
        elif c == curses.KEY_BACKSPACE or c == 127:
            shared_data['input_text'] = shared_data['input_text'][:-1]
        elif c == 27:  # Escape key.
            message_queue.put(('exit', 'system'))
            break
        elif c >= 32 and c <= 126:
            shared_data['input_text'] += chr(c)

        input_win.move(0, len("> ") + len(shared_data['input_text']))

def main(stdscr):
    # Clear the screen.
    os.system("printf '\33c\e[3J'")

    # Setup curses environment.
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Color for chatbot messages
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Color for user messages
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)  # Color for system messages

    # Hide the default cursor.
    curses.curs_set(0)

    # Get the screen dimensions.
    max_y, max_x = stdscr.getmaxyx()
    chat_height = max_y - 3

    # Create windows for chat and input.
    chat_win = curses.newwin(chat_height, max_x, 0, 0)
    input_win = curses.newwin(3, max_x, chat_height, 0)
    chat_win.scrollok(True)
    chat_win.idlok(True)

    # This queue will hold all the messages.
    message_queue = queue.Queue()

    # Shared data between threads.
    shared_data = {
        "running": False,
        "instruction": "Write blog article based on the document's title and instructions from the chat history."
    }

    # Start the chatbot and input threads.
    chatbot_thread = threading.Thread(target=chatbot, args=(message_queue, shared_data), daemon=True)
    chatbot_thread.start()

    input_thread = threading.Thread(target=input_loop, args=(stdscr, message_queue, chat_win, input_win, shared_data))
    input_thread.daemon = True
    input_thread.start()

    # Initialize a list to store messages and display them.
    messages = []
    while True:
        # Exit condition
        if not message_queue.empty() and message_queue.queue[0] == ('exit', 'system'):
            break
        
        # Handle new messages
        while not message_queue.empty():
            message, msg_type = message_queue.get()
            messages.append((message, msg_type))
            # Keep only the last chat_height messages.
            if len(messages) > chat_height - 1:
                messages.pop(0)
            chat_win.erase()

            # Display messages with different colors based on the message type.
            for i, (msg, msg_type) in enumerate(messages):
              wrapped_msg = textwrap.wrap(msg, width=max_x)
              for line in wrapped_msg:
                  if msg_type == 'chatbot':
                      chat_win.addstr(i, 0, line, curses.color_pair(1))
                      i += 1
                  elif msg_type == 'user':
                      chat_win.addstr(i, 0, line, curses.color_pair(2))
                      i += 1
                  elif msg_type == 'system':
                      chat_win.addstr(i, 0, line, curses.color_pair(3))
                      i += 1
            chat_win.refresh()

        # Always move the cursor back to the input window after chat window refresh.
        input_win.move(0, len("> ") + len(shared_data.get('input_text', '')))
        # Refresh the input window.
        input_win.refresh()
        # Sleep to reduce CPU usage.
        time.sleep(0.1)

wrapper(main)
