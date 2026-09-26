# First run: from installation to your first report

Follow this walkthrough on the computer where you want to run Labcat. It uses
Docker and your web browser; you do not need Python, Node, Rust, or a separate
Labcat desktop build. The same in-app steps apply to the native desktop window.

**Have ready:** an internet connection and either a supported ChatGPT account or
an API key from a supported model provider. A Materials Project key is optional.
Your selected provider runs the AI model and controls access, allowances and
charges. Docker runs the Labcat workspace locally.

Already running Labcat? Jump to [connect your model](#4-connect-your-model).
For image bundles, native builds and other installation routes, use the
[installation guide](installation.md).

## 1. Open a terminal and check the tools

1. Install [Git](https://git-scm.com/downloads) if it is not already installed.
2. On Mac or Windows, install and open
   [Docker Desktop](https://docs.docker.com/desktop/). Wait until its engine is
   running. On Windows, use **Linux containers**. On Linux, install and start
   [Docker Engine and Compose](installation.md#1-prepare-docker).
3. Open **Terminal** on Mac, **PowerShell** on Windows, or your Linux terminal.
   You can find Terminal or PowerShell using your computer's application search.
4. Copy each command below into that terminal and press **Enter**:

```text
git --version
docker info
docker compose version
```

**Check before continuing:** Git and Compose should print version information.
`docker info` should include information about a running Docker server. If a
command is not found, finish installing that tool and reopen your terminal. If
Docker cannot connect to its engine, start Docker and try again.

!!! tip "Where to type"
Terminal commands go in Terminal or PowerShell. Research questions go in
Labcat's chat box later. Copy only the commands inside the code blocks;
do not type terminal prompts such as `$` or `>`.

## 2. Download Labcat and build it

In the terminal, run:

```text
git clone https://github.com/kewh5868/labcat.git
cd labcat
docker build -t labcat:0.1.0.dev0 .
```

The first command creates a `labcat` folder in your current directory. The
second enters it. The third builds the application, including its dependencies.
Keep the final `.` in the build command. The first build can take several
minutes; wait for it to finish successfully and return to the terminal prompt.

If you already cloned Labcat, open a terminal in that existing folder and run
only the build command. The folder should contain `Dockerfile` and `compose.yaml`.
An existing installation can be updated using the
[update instructions](installation.md#saved-work-and-updates).

## 3. Open the application

From the same `labcat` folder, run the command for your operating system:

=== "Mac / Linux"

    ```sh
    ./labcat.sh --browser
    ```

=== "Windows PowerShell"

    ```powershell
    .\labcat.cmd -Browser
    ```

The launcher starts Labcat and opens a browser. If it does not open a window,
copy the local URL printed by the launcher into your browser's address bar.
Use the printed port; it can differ between installations.

**You should see:** the Labcat workspace and a setup dialog headed
**Connect your research model.**, with **Model**, **Compute**, **Public sources**
and **Ready** across the top. Keep Docker running for the following steps.

If setup is already complete, open **Connections** in the sidebar to review or
change your model connection. Do not rebuild the image each time you open Labcat.

## 4. Connect your model

In the **Model** setup step, open the **Model provider** dropdown. Choose one
of the routes below.

=== "ChatGPT account"

    1. Select **ChatGPT · account sign-in** in **Model provider**.
    2. Click **Sign in with ChatGPT**.
    3. Click **Open ChatGPT sign-in** if the provider page has not opened.
       Complete sign-in and authorization on the provider's page, then return
       to Labcat. Keep Labcat running while you connect.
    4. If Labcat displays a device code, enter it on the provider page as
       instructed. If the connection still says it is waiting after you finish,
       click **Check sign-in status**.
    5. Wait for the **Connected** badge and the available models to load.

    Your ChatGPT password belongs on the provider's sign-in page, never in
    Labcat. Account eligibility and available models depend on your provider.

=== "Provider API key"

    1. Choose your provider in **Model provider**, such as OpenAI API,
       Anthropic, Gemini or Kimi.
    2. Paste a key created in that provider's API dashboard into its **API key**
       field. A consumer chat subscription is not an API key.
    3. Click **Connect [provider]**. If updating a saved connection, the button
       says **Save API key**.
    4. Wait for the available models to load.

    API use follows that provider's billing. For Amazon Bedrock, use the
    separate [AWS profile setup instructions](aws.md).

Then complete these steps for either route:

1. Open the **Model** dropdown and select one of the returned models. If the list fails to
   load, check your connection and click **Refresh models**.
2. Read the consent notice, then check **I allow this provider to receive that
   context and run potentially billable planning calls.** to enable research.
3. Click **Save and test connections**. Wait for the connection check to finish.
4. When setup reports **Saved model connection verified**, click **Continue**.
   An existing saved connection may instead offer **Verify and continue**.

This check verifies account and model access; it does not run a research prompt.
If **Continue** is disabled, scroll through the model step, save any changed
model or consent setting, and resolve the displayed connection error. Clicking
**View workspace** closes the dialog but does not make an unverified connection
ready for research. [More connection help](onboarding.md)

## 5. Finish the optional setup steps

1. **Compute:** leave **Local workspace** as the default and leave
   **Configure Amazon Bedrock** unchecked for this walkthrough. Click
   **Continue**. Your chosen provider still runs the model; this does not
   install a local AI model.
2. **Public sources:** for a first run, keep the default public-source settings
   and click **Continue**. You can also click **Skip for now** to leave this
   optional step without applying unsaved changes.
3. **Ready:** check that the displayed model is the one you selected, then click
   **Finish setup**. The setup dialog closes and the workspace is ready for a
   question.

!!! tip "Optional: connect Materials Project"
In **Public sources**, find the Materials Project card. Use
**Register or get an API key** if needed, paste your key into its field, and
click **Save and verify**. Wait for verification before continuing. You can
add it later in **Connections**. Other supported public sources can be used
without this key; no source can guarantee a structure for every candidate.

## 6. Send your first research question

Use this example for your first run:

```text
I need an oxide for a very thin transistor insulating layer. Put a high
dielectric constant ahead of ease of manufacture, but include leakage and
room-temperature phase stability in the comparison. Explain the tradeoffs
and cite the evidence for each candidate.
```

1. Click **New chat** near the top of the left sidebar.
2. Click the box that says **What would you like to explore?** and paste the
   example question above.
3. Below the question, leave **Infer from prompt** selected for this first run.
   It lets Labcat infer supported ranking preferences from your request. Check
   that the model control shows the model you connected.
4. Leave **Find reference structures** checked if you want Labcat to look for
   available public reference structures alongside the report.
5. Click **Send** at the right of the question box. You can also press
   **Command + Enter** on Mac or **Ctrl + Enter** on Windows/Linux.

**You should see:** the chat gets a title and shows research progress. A bubbling
flask in the sidebar marks the running chat. You can open a different chat and
return while it works. Keep Docker and the Labcat backend running; stopping the
backend interrupts unfinished research.

If Labcat asks a clarification question, answer in the same chat box and click
**Send** again. Results depend on live sources and your model; this example does
not have a preset shortlist or a guaranteed number of matches.

## 7. Read the report and inspect a structure

Start with the report tabs below your research question:

1. Click **Summary**. Read the findings and candidate shortlist. Look at why
   each material is considered and its key caveats, including ties or missing
   evidence. Screening priority is not a measured performance percentage.
2. Click **Technical View** for candidate comparisons and available property
   evidence. Check whether the phase, conditions and material role fit your
   intended use.
3. Click **Sources** to inspect the references. Follow a source link or an
   inline citation to examine the evidence behind a claim.
4. In a shortlist, click **View structure** beneath a material when offered.
   Select a record if there are several. If the panel offers **Retrieve and
   view structure**, click it to fetch the coordinates and open the viewer.
5. In the JSmol viewer, drag to rotate and scroll to zoom. Use **Download CIF**
   or **Download displayed structure** to save the displayed geometry.

Read the structure's matching and phase labels. A bulk reference structure may
not represent the exact device phase, quantum dot, or core/shell interface.
If no file is found, the panel reports that limitation; a failed lookup is not
proof that no structure exists. [Structure help](structures.md)

## 8. Ask a follow-up or change priorities

In the same chat's question box, paste this follow-up and click **Send**:

```text
For the candidates above, compare the evidence for low leakage and
room-temperature phase stability. Which measurements are missing, and which
candidates should I investigate first?
```

The newest report becomes the main view. Click **Earlier questions**, then
**View saved report**, to revisit a previous question and its saved result.

For direct control over weights, open **Search Criterion** in the sidebar,
create and save a ranking profile, then choose that profile from the ranking
control below your next prompt. Run another question to apply it. Existing
reports are not recalculated when you edit a profile.
[Step-by-step ranking controls](user-guide.md#choose-criteria-and-change-their-influence)

To group your work, click **Create project** in the sidebar and fill in the
project form. You can move an existing chat using its three-dot menu and
**Move chat**. [Projects and saved history](projects.md)

## 9. Download your report

1. Beside the **Summary**, **Technical View** and **Sources** tabs, check the
   sections to include. Keep **Sources** checked to include the reference list.
   At least one section must be selected.
2. Open the format dropdown at the right of that row. Choose **PDF** for a
   shareable document, **Word (.docx)** for an editable document, **Plain text**
   for text, or **JSON** for structured data.
3. Click **Download**. Open the downloaded file from your browser's downloads.
   Structure CIF files are downloaded separately from their structure panels.

The checkboxes control the download, not which report tabs you can view. Changing
**Report Format** in the sidebar changes presentation, not evidence or rankings.

## 10. Stop and come back later

Closing the browser leaves Labcat running. To stop it, return to a terminal in
your `labcat` folder and run:

=== "Mac / Linux"

    ```sh
    ./labcat.sh stop
    ```

=== "Windows PowerShell"

    ```powershell
    .\labcat.cmd stop
    ```

This preserves saved chats and projects. Next time, start Docker and repeat the
[open command](#3-open-the-application). If you need the current local address,
run `./labcat.sh status` or `.\labcat.cmd status` from the same folder.

Credentials are session-only by default, so you may need to sign in again or
re-enter your API key after a backend restart. Optional encrypted storage is
available under **Advanced credential options**; a passphrase vault must be
unlocked after restart. Your saved research is independent of that sign-in.

Continue with [more example questions](examples.md), the
[workspace user guide](user-guide.md), or
[startup troubleshooting](deployment.md#troubleshooting).
