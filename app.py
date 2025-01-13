import json
import random

from flask import Flask, render_template, request
import os.path
import time

app = Flask(__name__)

with open("config.json", 'r') as config_file:
    config = json.loads(config_file.read())

def _selectRepeatWords(words : list):

    words = sorted(words, key=lambda x: x["nextRepeatTime"])[:config['WordsPerTry']]
    return list(filter(lambda x: x['nextRepeatTime'] < int(time.time()), words))



def _generateFirstStage(words, words2repeat):
    wordsrepeat = [w["word"] for w in words2repeat]
    words = list(filter(lambda x: x["word"] not in wordsrepeat, words))

    if len(words) == 0 or len(words2repeat) == 0:
        return []

    stage1 = []
    for w in words2repeat:
        options = random.sample(words, 3)
        insert_index = random.randint(0, 3)

        options.insert(insert_index, w)

        stage1.append({
            "translated": w["translation"],
            "options": options,
            "word": w
        })

    return stage1


def _checkDatabase():
    if not os.path.isfile("database.json"):
        _createDatabase()


def _createDatabase():
    f = open("database.json", "w", encoding="utf-8")
    f.write(json.dumps([]))
    f.close()


def _loadDatabase():
    with open("database.json", "r", encoding="utf-8") as f:
        words = json.loads(f.read())
        return words


def _updateWordsInDatabaseAndSave(words2update, words):
    for word in words2update:
        val = words2update[word]
        if type(val) == bool:
            # сохранение результата из повторения

            for w in words:
                if w["word"] == word:
                    wordDb = w

                    if not val:
                        wordDb["repeatIndex"] = 1
                    else:
                        wordDb["repeatIndex"] = int(wordDb["repeatIndex"]) + 1

                    wordDb["nextRepeatTime"] = _getRepeatDateFromRepeatIndex(wordDb["repeatIndex"])
                    break

        elif type(val) == str:
            words.append({
                "repeatIndex": 0,
                "translation": val,
                "word": word,
                "nextRepeatTime": 0
            })
    with open("database.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(words, indent=4))


def _getRepeatDateFromRepeatIndex(repeatIndex):
    days = 0
    if repeatIndex == 0:
        days = 0
    elif repeatIndex == 1:
        days = 1
    elif repeatIndex == 2:
        days = 2
    elif repeatIndex == 3:
        days = 3
    elif repeatIndex == 4:
        days = 7
    elif repeatIndex == 5:
        days = 14
    else:
        days = 14

    current_time = int(time.time())
    current_time += days * 86400

    return current_time


def _checkInput(words):
    words_to_add = dict()
    any_word_added = False

    if not os.path.isfile("database.json"):
        return

    with open("input.txt", encoding="utf-8") as f:
        for l in f:
            splitted = l.split("=")
            if len(splitted) < 2:
                continue

            word = splitted[0]
            word = word.strip()
            word = word.lower()
            translation = splitted[1]
            hint = ""

            for ww in words:
                if ww['word'] == word:
                    ww['translation'] = ww['translation'] + ", " + translation
                    break
            else:
                if len(splitted) == 3:
                    hint = splitted[2]

                words_to_add[word] = translation
            any_word_added = True

    with open("input.txt", "w", encoding="utf-8") as f:
        f.write("")

    if any_word_added:
        _updateWordsInDatabaseAndSave(words_to_add, words)


@app.route('/', methods=['POST', 'GET'])
def hello_world():  # put application's code here

    _checkDatabase()
    words = _loadDatabase()

    if request.method == 'POST':
        json_data = json.loads(request.get_data().decode('utf-8'))
        _updateWordsInDatabaseAndSave(json_data, words)

        return json.dumps({"success": True})

    _checkInput(words)

    words2repeat = _selectRepeatWords(words)

    firstStage = _generateFirstStage(words, words2repeat)

    return render_template("index.html", data={
        "firstStage": firstStage,
        "words": words2repeat
    })


if __name__ == '__main__':
    app.run()
