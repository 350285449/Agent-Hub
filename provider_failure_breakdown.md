# Provider Failure Breakdown

| provider/agent | calls | valid structured outputs | completed rows | quarantined rows | notes |
| --- | ---: | ---: | ---: | ---: | --- |
| no_completed_call | 0 | 0 | 0 | 1 | - |
| ollama-gemma-cloud | 38 | 38 | 19 | 0 | - |

## Failover / Provider Blocks

| agent | error type | count | reason excerpt |
| --- | --- | ---: | --- |
| ollama-nemotron-cloud | unknown | 24 | Agent is in temporary cooldown from a previous failure |
| ollama-qwen-cloud | unknown | 13 | Agent is in temporary cooldown from a previous failure |
| ollama-kimi-cloud | unknown | 13 | Agent is in temporary cooldown from a previous failure |
| ollama-glm-cloud | unknown | 13 | Agent is in temporary cooldown from a previous failure |
| ollama-nemotron-cloud | output_too_large | 4 | Agent stopped because it hit an output token limit; continuing with the next configured agent |
| ollama-nemotron-cloud | invalid_provider_response | 3 | Provider returned invalid response: missing_content_or_tool_calls |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: a6e086e1-677c-4ad8-8301-1e1cebd12b56) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 649e65a1-7cb6-4211-b05c-49c2da19be77) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: b857e21d-622a-4835-897b-c2e1b1c721b8) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 6f72ec7b-ac42-4480-891b-0d5852339936) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 20eb4089-9255-44ff-8662-c8101d2464bf) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 2db9b0ba-d43f-41ef-af7a-df20a601baea) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: e41412cb-412d-4664-be35-a99544b55cfc) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 5f34fe54-c2b8-4711-901b-4cc138a85794) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 0c23fd90-4aaa-40d1-9d45-495201425c31) |
| ollama-nemotron-cloud | provider_overloaded | 1 | Provider response latency exceeded failover threshold: 23.49s > 20.00s |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 8a49e8bd-ecbc-4ee2-8169-075184940101) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: a4ccbd99-1245-4b1d-8773-c973a84d51cc) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 2c376f90-d78d-4e1c-be95-f5200dbe44f4) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 5d5a4a98-91ce-4094-aa86-b1ba8e11545e) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 794f4bbb-ce36-41b1-9c4a-3a255fc09b5e) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: da17f968-b5c2-433f-b0b0-3b8832e3a423) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: a4729c61-056c-4f88-bb17-113888391a2e) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 34afd39a-821a-4bb4-97a4-aa22ae81e8cc) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 08757edc-ade4-4480-a588-f7355ed7cba6) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: be22e7ba-65fe-406b-b732-c7fd1c73aaf2) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: c631742f-d098-437b-a5e1-75b03417a848) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: daf5a786-df90-4fa1-82eb-388445969303) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: d5969852-1f49-443a-abe8-a723f9bdfe6b) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 2dc7095c-6f2c-4db2-99d4-417394ff467f) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: c208c0b0-d03f-4be5-9372-a32a21c8b030) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: d290fbed-77b9-4694-ba88-a457d755e2a9) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 74cfcb9e-0940-4ed4-98a6-79af0a4f7f41) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 8d0266ca-4288-47ee-b8a3-6bd3006eb85a) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 355149e5-006f-447f-a999-422519983a77) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 4d710da7-135f-4ca6-ab95-091ae18eb388) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: e0b37a75-acab-4477-915d-10698dea17c3) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 260ab805-c1dd-4453-a725-9420dd11bdde) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: f163db38-f88b-44d5-a655-89907cfc7620) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 1cf059e8-91ef-482c-9983-78adb3cc8f2d) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 540c51ce-cd09-46bf-93e8-3e8b17e73a5a) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 057251a8-4bbe-4a56-8023-1bed55f83d01) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 1ed44285-c088-420e-9f9d-d2e6cf94ab73) |
| ollama-nemotron-cloud | provider_overloaded | 1 | Provider average latency is degraded: 34.82s average |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 720cee28-ac66-4606-8ed0-6b967744186a) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 4600937f-542d-4245-bdc5-a7a013264382) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 8ec18cba-da3c-4c66-bf2e-fff57b85f3d5) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: ee2f36b8-e9de-497b-ada4-d3516314f2ce) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 50d6da57-bd53-4f04-810a-f7c6f85333e5) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 2d5398a0-c1a7-4814-a62f-94beb004c265) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 5ebc9c6e-1a0a-4915-99fa-fec5e16cbd85) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 820b83b7-4783-4c8e-a984-b335f4238fb7) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: fb4ff603-97d8-4b40-adf6-6a9b71c09db9) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: c3e4b9fd-bb5b-413d-bcbb-47ac2f4daac9) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 41c859e6-c946-444e-8efd-9130e0ee7ef5) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 0e555b24-e835-4fee-84e9-734f3bde234b) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: aaff60f7-77d2-42e9-8680-8f8488fa81cb) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: aa45b6f4-84f6-45fb-b649-7678d3b1e6a4) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 93799968-ea36-4858-878a-4917c9ae8fb2) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 220db135-7b50-44d8-b434-ba1b5da4984a) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 431fb81c-03ec-4727-a81b-d7f9030343a6) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: a42d8162-5923-46b0-8154-05148800fb99) |
| ollama-nemotron-cloud | provider_overloaded | 1 | Provider response latency exceeded failover threshold: 58.54s > 20.00s |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 0d4f4274-4c2c-4620-8716-cb9ef72d4721) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 88097f29-46a6-47de-9eda-c5481581cc17) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 8323981e-cdc7-4c1b-8802-97fc952b2fd1) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: d6ee9065-3106-4cff-a105-847bef217dbd) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 283f262b-96c2-43f9-8d75-a97a7dd08416) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 0bc931d1-ed03-4ef0-979b-afb509d5e271) |
| ollama-kimi-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: cb3d9a5a-8ca7-46f3-a3e9-95cf3fe2696b) |
| ollama-glm-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: be8d03b1-560e-48e9-8a8f-22d028962da8) |
| ollama-qwen-cloud | authentication_error | 1 | this model requires a subscription, upgrade for access: https://ollama.com/upgrade (ref: 74204ccb-8c84-4aec-93e5-9d1954df160c) |
