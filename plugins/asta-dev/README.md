# asta-dev plugin

This plugin contains information for developers of this repo, and for internal Ai2 users.

## Skills
 
- `research-challenge` for submitting your project to the [research challenge](https://allenai.slack.com/archives/C0AQJH866VA)
- `improve-skills` for benchmarking and automated improvement of the plugin skills

## Slack/GitHub integration

Use the `@gas2own` alias in Slack to message a remote agent with the asta plugins that can make changes
to your project in GitHub.

 1. In your Slack channel `/invite @gas2own`
 1. Bind the Slack channel to a GitHub repo: `/topic repo:<your-research-repo-url>`
 1. In your GitHub repo add the `@gas2own` user as a collaborator with maintain permissions
    (Goto GitHub repo Web page -> Settings -> Collaborators and teams -> Add people -> gas2own -> check "Maintain")
 1. Tag the agent in Slack: `@gas2own show me related literature as an asta workspace`

### Workspaces

Asking the agent to set up an "asta workspace" will trigger the `asta-tools:workspace` skill.
This will set up a persistent document server for the project. Artifacts created by humans or agents
will be checked into the repo and published on a `github.io` URL

### Example

 - Slack channel: [#ai-for-science-survey](https://allenai.slack.com/archives/C0APB5FEZSA)
 - Repo: [ai-for-science-survey](https://github.com/allenai/ai-for-science-survey)
 - Workspace: [http://allenai.github.io/ai-for-science-survey](http://allenai.github.io/ai-for-science-survey)
