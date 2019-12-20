import configparser
import json
import os
import sys

import requests
import slack

config = configparser.ConfigParser()
config.read(".gerritbutler.config")
sections = config.sections()

slack_token = os.environ.get("GERRIT_BUTLER_TOKEN")
if slack_token is None:
    try:
        slack_token = config["GERRIT"]["GERRIT_BUTLER_TOKEN"]
    except KeyError:
        print("Missing variable: 'GERRIT_BUTLER_TOKEN'")
        sys.exit(1)

try:
    gerrit_url = config["GERRIT"]["URL"]
    gerrit_username = config["GERRIT"]["USERNAME"]
    gerrit_password = config["GERRIT"]["PASSWORD"]
except KeyError:
    print("Missing variable in config file")
    sys.exit(1)

projects = {}

for project_name in sections:
    if project_name != "GERRIT":
        projects[project_name] = config[project_name]["OPTIONS"]

rtmclient = slack.RTMClient(token=slack_token)
auth = requests.auth.HTTPBasicAuth(gerrit_username, gerrit_password)


def get_open_patchsets():
    results = {}
    authors = {}
    for project_name, options in projects.items():
        results[project_name] = []

        response = requests.get(
            f"{gerrit_url}/a/changes/?q=project:{project_name}{options}", auth=auth
        )
        data = json.loads(response.content.decode("utf-8")[5:])

        for item in data:
            patchset = {}
            patchset["title"] = item["subject"]

            author = str(item["owner"]["_account_id"])
            if author not in authors:
                author_response = requests.get(
                    f"{gerrit_url}/accounts/{author}/username/"
                ).content.decode("utf-8")[5:-1]
                authors[author] = author_response.replace('"', "")
            patchset["author"] = authors[author]
            patchset["url"] = f"{gerrit_url}/#/c/{project_name}/+/{item['_number']}/"
            results[project_name].append(patchset)
    return results


def create_changes_message(project, changes):
    message = f":computer: {project}\n"
    for change in changes:
        message += f"Title: {change['title']}\n"
        message += f"Author: @{change['author']}\n"
        message += f"URL: {change['url']}\n\n"
    return message


@slack.RTMClient.run_on(event="message")
def parse_bot_mentions(**payload):
    data = payload["data"]
    if "subtype" not in data:
        webclient = payload["web_client"]
        slackbot_user_id = webclient.auth_test()["user_id"]

        if slackbot_user_id in data["text"]:
            channel_id = data["channel"]
            thread_ts = data.get("thread_ts", None)
            open_patchsets = get_open_patchsets()
            if all(value == [] for value in open_patchsets.values()):
                webclient.chat_postMessage(
                    channel=channel_id,
                    text="Congrats, there are no pending patchsets!\n",
                    thread_ts=thread_ts,
                )
            else:
                opening_message = webclient.chat_postMessage(
                    channel=channel_id,
                    text="Here are today's open patchsets!\n",
                    thread_ts=thread_ts,
                )

                for key, value in open_patchsets.items():
                    if value != []:
                        # Sends the response back to the channel
                        webclient.chat_postMessage(
                            channel=channel_id,
                            text=create_changes_message(key, value),
                            thread_ts=opening_message['ts'],
                        )


if __name__ == "__main__":
    rtmclient.start()
