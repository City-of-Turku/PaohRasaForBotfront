# PaohRasaForBotfront

# Rasa for Botfront

This repository contains a fork of Rasa to be used with Botfront. This is based on [Botfront's fork](https://github.com/botfront/rasa-for-botfront) but with updated Rasa version (2.3 -> 2.8) and some memory optimizations.

**Note**: Docker build of this repo acts as the "base" image for [RasaPlatform](https://dev.azure.com/turunkaupunki/VmPalvelukonsolidaatio/_git/RasaPlatform) repo's Rasa Docker build. Docker build of this repo takes longer and this repo needs less mofidications so that's why it acts as the "base" image. [RasaPlatform](https://dev.azure.com/turunkaupunki/VmPalvelukonsolidaatio/_git/RasaPlatform) repo's Rasa contains a few addons for Rasa which are more actively developed and quicker to build so that repo will finally deploy the Rasa to Azure AKS environment.

# Documentation

The [official documentation](https://rasa.com/docs/rasa/2.x) of Rasa is hosted on [https://rasa.com/docs/rasa/2.x](https://rasa.com/docs/rasa/2.x)

# Deploying to Azure cloud

The docker images are build and pushed to the test and production Azure Container Registry (to act as "base" image for the [RasaPlatform](https://dev.azure.com/turunkaupunki/VmPalvelukonsolidaatio/_git/RasaPlatform) repo's Rasa Docker build) from `dev` and `main` branches respectively. The pipeline uses Azure Container registry to store created images. The connection credentials are a part of the pipeline and those are fetched from Azure Key Vault.

To run the deployment it is enough to merge to `dev` and `main` branches after which new version is deployed.

The Azure Devops pipeline is defined in `azure-pipelines.yml` file.

# Development locally

## How to build rasa-for-botfront locally

You can build docker image by running `docker build -f docker/Dockerfile.botfront -t rasa-for-botfront .` and then run the container with Botfront or use the image as the base for building custom rasa-for-botfront images with, for example, custom addons in [RasaPlatform](https://dev.azure.com/turunkaupunki/VmPalvelukonsolidaatio/_git/RasaPlatform) repository.

## How to develop Rasa locally

1. Rasa uses Python so install Python version (3.7 - 3.9) first
2. Rasa uses Poetry for Python packaging and dependency management. You have to install Poetry first: [https://python-poetry.org/docs/#installation](https://python-poetry.org/docs/#installation)
3. Run commands `poetry shell` and `poetry install` to install dependencies
4. If you want use Rasa with Botfront, have [Botfront](https://dev.azure.com/turunkaupunki/VmPalvelukonsolidaatio/_git/Botfront) running first and then set environment variables for Rasa's startup: `export BF_URL=http://localhost:3000/graphql` and `export BF_PROJECT_ID=YOUR_BOTFRONT_PROJECT_ID` so Rasa will fetch needed configs from Botfront project on startup
4. Run command `rasa run --enable-api --debug` to start the Rasa server


# Custom modifications made for Palveluohjaaja

## Update Rasa's slots from the Palveluohjaaja' web front-end

Palveluohjaaja web front-end sends information about end-user's language and municipality choices to be used in Rasa's slots. Information is sent through the websocket channel on the fly when end-user changes their language or municipality choices. The front-end will also send information whether it wants Rasa bot to show service recommendation cards or not (based on end-user's browser size).

This information is updated to Rasa's slots called `municipality` for municipality, `session_started_metadata` for language, and `show_recommendations` for showing the service recommendation cards. Updating happens on every conversation turn (user sends message and bot responds) and the updating functionality has been implemented in `rasa/core/channels/channel.py` file on rows 89-114. Here is the current code:

```python
if app.agent.tracker_store.exists(message.sender_id):
    tracker = app.agent.tracker_store.retrieve(message.sender_id)
    if tracker:
        # update municipality slot if changed from the frontend
        if tracker.get_slot("municipality") != message.metadata.get("municipality"):
            tracker.update(SlotSet('municipality', message.metadata.get("municipality")))
            app.agent.tracker_store.save(tracker)

        # update show_recommendations slot if changed from the frontend
        if tracker.get_slot("show_recommendations") != message.metadata.get("show_recommendations"):
            tracker.update(SlotSet('show_recommendations', message.metadata.get("show_recommendations")))
            app.agent.tracker_store.save(tracker)

        # let's also update session_started_metadata language to get Rasa ReminderScheduled action to show correct lang response
        session_started_metadata = tracker.get_slot("session_started_metadata")
        latest_msg_lang = message.metadata.get("language")
        if latest_msg_lang and isinstance(session_started_metadata, dict) and latest_msg_lang != session_started_metadata.get("language", None):
            session_started_metadata["language"] = latest_msg_lang
            tracker.update(SlotSet('session_started_metadata', session_started_metadata))
            app.agent.tracker_store.save(tracker)
```

## Rasa bot production deployment endpoint for Botfront's deployment webhook feature

Botfront has feature for utilizing two Rasa containers where one is for "development" bot and the other is for the "production" bot. When the developer of the bot has created new version with the "development" Rasa and wants to deploy it to the "production" Rasa, Botfront will call deployment webhook. At Palveluohjaaja, endpoint for that webhook was simply implemented into Rasa's existing REST API. Implemented webhook will try copy the "development" Rasa bot model file to the "production" Rasa bot and load the model into "production" Rasa's use. Thus, there are two different volumes mounted into Rasa container, one is the Azure File Share of the "development" Rasa and the other is the Azure File Share of the "production" Rasa. For both Rasas, their "main" volume is mounted to the Rasa's default `/app/models` path and then the "development" Rasa's volume is also mounted to the different `/app/models-dev` path. Then the implemented deployment endpoint will try copy the new Rasa model file from path defined in `DEV_MODELS_PATH` environment variable (whose value is `/app/models-dev`) to the main volume path `/app/models`.

The implemented endpoint is in `rasa/server.py` file on rows 1133-1169. Here is the current code:

```python
@app.get("/botfront/deploy")
@requires_auth(app, auth_token)
@async_if_callback_url
@run_in_thread
async def botfront_deploy(request: Request) -> HTTPResponse:
    try:
        dev_models_path = os.environ.get("DEV_MODELS_PATH", None)
        if dev_models_path:
            dev_models_path = os.path.join(dev_models_path, app.agent.path_to_model_archive.split("/")[-1])
        else:
            return response.json({"detail": "Cannot find DEV_MODELS_PATH to use for deploying newly trained model"}, status=500)
        
        try:
            shutil.copyfile(dev_models_path, app.agent.path_to_model_archive)
        except shutil.SameFileError:
            pass

        previous_model_tmp_dir = app.agent.model_directory
        app.agent = await _load_agent(
            app.agent.path_to_model_archive,
            endpoints=endpoints,
            lock_store=app.agent.lock_store,
            agent_interpreter=app.agent.interpreter if previous_model_tmp_dir else None,
            after_training_load=True if previous_model_tmp_dir else False
        )

        logger.info(f"Successfully loaded deployed model to production.")
        if previous_model_tmp_dir:
            shutil.rmtree(previous_model_tmp_dir, ignore_errors=True)
            logger.debug(f"Successfully removed previous model tmp dir: {previous_model_tmp_dir}")

        return response.json({"message": "Successfully deployed to production"})


    except Exception as e:
        logger.error(traceback.format_exc())
        return response.json({"detail": str(e)}, status=500)
```


# Botfront's info about their Rasa Addons (might be bit legacy stuff and not needed anymore)

## rasa_addons.core.policies.BotfrontDisambiguationPolicy

This policy implements fallback and suggestion-based disambiguation.

It works with actions ``rasa_addons.core.actions.ActionBotfrontDisambiguation``, ``rasa_addons.core.actions.ActionBotfrontDisambiguationFollowup`` and ``rasa_addons.core.actions.ActionBotfrontFallback``, and NLU pipeline component ``rasa_addons.nlu.components.intent_ranking_canonical_example_injector.IntentRankingCanonicalExampleInjector``.

### Example usage

```yaml
policies:
  ...
  - name: rasa_addons.core.policies.BotfrontDisambiguationPolicy
    fallback_trigger: 0.30 # default value
    disambiguation_trigger: '$0 < 2 * $1' # default value
    disambiguation_template: 'utter_disambiguation' # default value
    n_suggestions: 2 # default value
    excluded_intents:
      - ^chitchat\..* # default value
      - ^basics\..*
  ...
```

### Note: Automatic generation of suggestion button titles

Botfront introduces the notion of "canonical" training examples, which provide a canonical human-readable text for intent labels. For example, for an intent ``pay_bills`` with examples "Pay bills", "I want to pay my bills", "How does one pay the bills on this website?", the first example may be selected as canonical. Canonical status serves as a cue to the bot designer, since intent labels can become untractable over time. It may also come to serve more Botfront-internal roles in the future.

The Botfront Disambiguation Policy uses canonical status to provide localized text for the suggestion buttons shown to users during disambiguation. In order to enable this feature, the NLU pipeline for each language model needs to be extended in the following way:

```yaml
pipeline:
  ...
  - name: rasa_addons.nlu.components.intent_ranking_canonical_example_injector.IntentRankingCanonicalExampleInjector
  ...
```

This NLU component enriches the ``intent_ranking`` key of user messages in the tracker with canonical text, so that the Disambiguation Policy may pick it up. If the NLU component is not used, buttons will have the intent name as their title.

### Parameters

##### fallback_trigger

Float (default ``0.30``): if confidence of top-ranking intent is below this threshold, fallback is triggered. Fallback is an action that utters the template ``utter_fallback`` and returns to the previous conversation state.

##### disambiguation_trigger

String (default ``'$0 < 2 * $1'``): if this expression holds, disambiguation is triggered. (If it has already been triggered on the previous turn, fallback is triggered instead.) Here this expression resolves to "the score of the top-ranking intent is below twice the score of the second-ranking intent". Disambiguation is an action that lets the user to choose from the top-ranking intents using a button prompt.

##### disambiguation_template

String (default ``'utter_disambiguation'``): a response name resolving to a template containing a ``text`` field with a message, e.g. "I could not quite understand. Did you mean...". Any button included under the ``buttons`` field of this template will also appear at the end of autogenerated suggestions, e.g. ``{"title": "None of the above", "type": "postback", "payload": "/deny_suggestions"}``.

##### n_suggestions

Int (default ``2``): the maximum number of suggestions to display (excluding the 'Other' options).

##### excluded_intents

List (default ``["^chitchat\..*", "^basics\..*"]``): any intent (exactly) matching one of these regular expressions will not be shown as a suggestion.

## rasa_addons.core.policies.BotfrontMappingPolicy

This policy implements regular expression-based direct mapping from intent to action.

### Example usage

```yaml
policies:
  ...
  - name: rasa_addons.core.policies.BotfrontMappingPolicy
    triggers:
      - trigger: '^map\..+'
        action: 'action_botfront_mapping'
        extra_actions:
          - 'action_myaction'
  ...
```

### ActionBotfrontMapping

The default action ActionBotfrontMapping takes the intent that triggered the mapping policy, e.g. ``map.my_intent`` and tries to generate the template ``utter_map.my_intent``.

## rasa_addons.core.channels.webchat.WebchatInput

### Example usage

```yaml
credentials:
  ...
  rasa_addons.core.channels.webchat.WebchatInput:
    session_persistence: true
    base_url: {{rasa_url}}
    socket_path: '/socket.io/'
  ...
```

## rasa_addons.core.channels.rest.BotfrontRestInput

Rest Input Channel with multilanguage and metadata support.

### Example usage

```yaml
credentials:
  ...
  rasa_addons.core.channels.rest.BotfrontRestInput:
    # POST {{rasa_url}}/webhooks/rest/webhook/
  ...
```

## rasa_addons.core.channels.bot_regression_test.BotRegressionTestInput:
Conversation testing channel. Simulates each user event in the input test stories as a message sent by a user, then compares the input story to the results from rasa. Returns a diff of the input story and output story with expected and actual events.

## Example usage

```yaml
credentials:
  ...
  rasa_addons.core.channels.bot_regression_test.BotRegressionTestInput: {}
    # POST {{rasa_url}} /webhooks/bot_regression_test/run
  ...
```

## rasa_addons.core.nlg.BotfrontTemplatedNaturalLanguageGenerator

Idential to Rasa's `TemplatedNaturalLanguageGenerator`, except in handles templates with a language key.

## rasa_addons.core.nlg.GraphQLNaturalLanguageGenerator

The new standard way to connect to the Botfront NLG endpoint. Note that support for the legacy REST endpoint is maintained for the moment. This feature is accessed by supplying a URL that doesn't contain the substring "graphql".

### Example usage

```yaml
endpoints:
  ...
  nlg:
    url: 'http://localhost:3000/graphql'
    type: 'rasa_addons.core.nlg.GraphQLNaturalLanguageGenerator'
  ...
```
make types
```
