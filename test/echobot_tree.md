├── assets/
│   ├── banner.jpg
│   ├── channel_qq_1.png
│   ├── channel_qq_2.png
│   ├── channel_qq_3.jpg
│   ├── webui_1.png
│   ├── webui_background.png
│   ├── webui_cron.png
│   ├── webui_custom_1.png
│   ├── webui_file.png
│   ├── webui_heartbeat.png
│   ├── webui_image_1.png
│   ├── webui_image_2.png
│   ├── webui_light_off.png
│   ├── webui_light_on.png
│   ├── webui_light.png
│   ├── webui_live2d.png
│   ├── webui_router.png
│   └── webui_tts.png
├── echobot/
│   ├── app/
│   │   ├── builtin_live2d/
│   │   │   ├── hiyori_pro_en/
│   │   │   │   ├── runtime/
│   │   │   │   │   ├── hiyori_pro_t11.2048/
│   │   │   │   │   │   ├── texture_00.png
│   │   │   │   │   │   └── texture_01.png
│   │   │   │   │   ├── motion/
│   │   │   │   │   │   ├── hiyori_m01.motion3.json
│   │   │   │   │   │   ├── hiyori_m02.motion3.json
│   │   │   │   │   │   ├── hiyori_m03.motion3.json
│   │   │   │   │   │   ├── hiyori_m04.motion3.json
│   │   │   │   │   │   ├── hiyori_m05.motion3.json
│   │   │   │   │   │   ├── hiyori_m06.motion3.json
│   │   │   │   │   │   ├── hiyori_m07.motion3.json
│   │   │   │   │   │   ├── hiyori_m08.motion3.json
│   │   │   │   │   │   ├── hiyori_m09.motion3.json
│   │   │   │   │   │   └── hiyori_m10.motion3.json
│   │   │   │   │   ├── hiyori_pro_t11.cdi3.json
│   │   │   │   │   ├── hiyori_pro_t11.moc3
│   │   │   │   │   ├── hiyori_pro_t11.model3.json
│   │   │   │   │   ├── hiyori_pro_t11.physics3.json
│   │   │   │   │   └── hiyori_pro_t11.pose3.json
│   │   │   │   └── ReadMe.txt
│   │   │   └── mao_pro_en/
│   │   │       ├── runtime/
│   │   │       │   ├── expressions/
│   │   │       │   │   ├── exp_01.exp3.json
│   │   │       │   │   ├── exp_02.exp3.json
│   │   │       │   │   ├── exp_03.exp3.json
│   │   │       │   │   ├── exp_04.exp3.json
│   │   │       │   │   ├── exp_05.exp3.json
│   │   │       │   │   ├── exp_06.exp3.json
│   │   │       │   │   ├── exp_07.exp3.json
│   │   │       │   │   └── exp_08.exp3.json
│   │   │       │   ├── mao_pro.4096/
│   │   │       │   │   └── texture_00.png
│   │   │       │   ├── motions/
│   │   │       │   │   ├── mtn_01.motion3.json
│   │   │       │   │   ├── mtn_02.motion3.json
│   │   │       │   │   ├── mtn_03.motion3.json
│   │   │       │   │   ├── mtn_04.motion3.json
│   │   │       │   │   ├── special_01.motion3.json
│   │   │       │   │   ├── special_02.motion3.json
│   │   │       │   │   └── special_03.motion3.json
│   │   │       │   ├── mao_pro.cdi3.json
│   │   │       │   ├── mao_pro.moc3
│   │   │       │   ├── mao_pro.model3.json
│   │   │       │   ├── mao_pro.physics3.json
│   │   │       │   └── mao_pro.pose3.json
│   │   │       └── ReadMe.txt
│   │   ├── builtin_stage_backgrounds/
│   │   │   ├── background-1.jpg
│   │   │   └── background-2.jpg
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── attachments.py
│   │   │   ├── channels.py
│   │   │   ├── chat.py
│   │   │   ├── cron.py
│   │   │   ├── health.py
│   │   │   ├── heartbeat.py
│   │   │   ├── roles.py
│   │   │   ├── sessions.py
│   │   │   └── web.py
│   │   ├── services/
│   │   │   ├── web_console/
│   │   │   │   ├── live2d/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── annotations.py
│   │   │   │   │   ├── catalog.py
│   │   │   │   │   ├── constants.py
│   │   │   │   │   ├── metadata.py
│   │   │   │   │   ├── models.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   └── uploads.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── service.py
│   │   │   │   ├── settings.py
│   │   │   │   └── stage.py
│   │   │   ├── __init__.py
│   │   │   ├── channels.py
│   │   │   ├── chat.py
│   │   │   └── roles.py
│   │   ├── web/
│   │   │   ├── bootstrap/
│   │   │   │   ├── ui-status.js
│   │   │   │   └── wire-events.js
│   │   │   ├── core/
│   │   │   │   ├── dom.js
│   │   │   │   ├── storage.js
│   │   │   │   └── store.js
│   │   │   ├── features/
│   │   │   │   ├── asr/
│   │   │   │   │   ├── audio.js
│   │   │   │   │   ├── config.js
│   │   │   │   │   ├── prompts.js
│   │   │   │   │   └── realtime.js
│   │   │   │   ├── chat/
│   │   │   │   │   ├── composer-attachments.js
│   │   │   │   │   ├── index.js
│   │   │   │   │   └── job-runner.js
│   │   │   │   ├── layout/
│   │   │   │   │   ├── cron.js
│   │   │   │   │   ├── heartbeat.js
│   │   │   │   │   ├── index.js
│   │   │   │   │   ├── panels.js
│   │   │   │   │   ├── runtime.js
│   │   │   │   │   ├── sidebars.js
│   │   │   │   │   └── split.js
│   │   │   │   ├── live2d/
│   │   │   │   │   ├── controls/
│   │   │   │   │   │   ├── common.js
│   │   │   │   │   │   ├── persistence.js
│   │   │   │   │   │   ├── render.js
│   │   │   │   │   │   └── runtime.js
│   │   │   │   │   ├── backgrounds.js
│   │   │   │   │   ├── config.js
│   │   │   │   │   ├── constants.js
│   │   │   │   │   ├── controls.js
│   │   │   │   │   ├── effects.js
│   │   │   │   │   ├── index.js
│   │   │   │   │   ├── model.js
│   │   │   │   │   ├── scene.js
│   │   │   │   │   └── schema.js
│   │   │   │   ├── sessions/
│   │   │   │   │   ├── api.js
│   │   │   │   │   ├── history.js
│   │   │   │   │   ├── route-mode.js
│   │   │   │   │   └── sidebar.js
│   │   │   │   ├── tts/
│   │   │   │   │   ├── options.js
│   │   │   │   │   ├── playback.js
│   │   │   │   │   └── text.js
│   │   │   │   ├── asr.js
│   │   │   │   ├── roles.js
│   │   │   │   ├── sessions.js
│   │   │   │   └── tts.js
│   │   │   ├── modules/
│   │   │   │   ├── api.js
│   │   │   │   ├── content.js
│   │   │   │   ├── markdown.js
│   │   │   │   ├── math.js
│   │   │   │   ├── messages.js
│   │   │   │   ├── traces.js
│   │   │   │   └── utils.js
│   │   │   ├── styles/
│   │   │   │   ├── base.css
│   │   │   │   ├── composer.css
│   │   │   │   ├── index.css
│   │   │   │   ├── messages.css
│   │   │   │   ├── panels.css
│   │   │   │   ├── responsive.css
│   │   │   │   └── stage.css
│   │   │   ├── vendor/
│   │   │   │   ├── mathjax/
│   │   │   │   │   ├── a11y/
│   │   │   │   │   │   ├── assistive-mml.js
│   │   │   │   │   │   ├── complexity.js
│   │   │   │   │   │   ├── explorer.js
│   │   │   │   │   │   ├── semantic-enrich.js
│   │   │   │   │   │   ├── speech.js
│   │   │   │   │   │   └── sre.js
│   │   │   │   │   ├── adaptors/
│   │   │   │   │   │   ├── jsdom.js
│   │   │   │   │   │   ├── linkedom.js
│   │   │   │   │   │   └── liteDOM.js
│   │   │   │   │   ├── input/
│   │   │   │   │   │   ├── mml/
│   │   │   │   │   │   │   ├── extensions/
│   │   │   │   │   │   │   │   ├── mml3.js
│   │   │   │   │   │   │   │   └── mml3.sef.json
│   │   │   │   │   │   │   └── entities.js
│   │   │   │   │   │   ├── tex/
│   │   │   │   │   │   │   └── extensions/
│   │   │   │   │   │   │       ├── action.js
│   │   │   │   │   │   │       ├── ams.js
│   │   │   │   │   │   │       ├── amscd.js
│   │   │   │   │   │   │       ├── autoload.js
│   │   │   │   │   │   │       ├── bbm.js
│   │   │   │   │   │   │       ├── bboldx.js
│   │   │   │   │   │   │       ├── bbox.js
│   │   │   │   │   │   │       ├── begingroup.js
│   │   │   │   │   │   │       ├── boldsymbol.js
│   │   │   │   │   │   │       ├── braket.js
│   │   │   │   │   │   │       ├── bussproofs.js
│   │   │   │   │   │   │       ├── cancel.js
│   │   │   │   │   │   │       ├── cases.js
│   │   │   │   │   │   │       ├── centernot.js
│   │   │   │   │   │   │       ├── color.js
│   │   │   │   │   │   │       ├── colortbl.js
│   │   │   │   │   │   │       ├── colorv2.js
│   │   │   │   │   │   │       ├── configmacros.js
│   │   │   │   │   │   │       ├── dsfont.js
│   │   │   │   │   │   │       ├── empheq.js
│   │   │   │   │   │   │       ├── enclose.js
│   │   │   │   │   │   │       ├── extpfeil.js
│   │   │   │   │   │   │       ├── gensymb.js
│   │   │   │   │   │   │       ├── html.js
│   │   │   │   │   │   │       ├── mathtools.js
│   │   │   │   │   │   │       ├── mhchem.js
│   │   │   │   │   │   │       ├── newcommand.js
│   │   │   │   │   │   │       ├── noerrors.js
│   │   │   │   │   │   │       ├── noundefined.js
│   │   │   │   │   │   │       ├── physics.js
│   │   │   │   │   │   │       ├── require.js
│   │   │   │   │   │   │       ├── setoptions.js
│   │   │   │   │   │   │       ├── tagformat.js
│   │   │   │   │   │   │       ├── texhtml.js
│   │   │   │   │   │   │       ├── textcomp.js
│   │   │   │   │   │   │       ├── textmacros.js
│   │   │   │   │   │   │       ├── unicode.js
│   │   │   │   │   │   │       ├── units.js
│   │   │   │   │   │   │       ├── upgreek.js
│   │   │   │   │   │   │       └── verb.js
│   │   │   │   │   │   ├── asciimath.js
│   │   │   │   │   │   ├── mml.js
│   │   │   │   │   │   ├── tex-base.js
│   │   │   │   │   │   └── tex.js
│   │   │   │   │   ├── output/
│   │   │   │   │   │   ├── chtml.js
│   │   │   │   │   │   └── svg.js
│   │   │   │   │   ├── sre/
│   │   │   │   │   │   ├── mathmaps/
│   │   │   │   │   │   │   ├── af.json
│   │   │   │   │   │   │   ├── base.json
│   │   │   │   │   │   │   ├── ca.json
│   │   │   │   │   │   │   ├── da.json
│   │   │   │   │   │   │   ├── de.json
│   │   │   │   │   │   │   ├── en.json
│   │   │   │   │   │   │   ├── es.json
│   │   │   │   │   │   │   ├── euro.json
│   │   │   │   │   │   │   ├── fr.json
│   │   │   │   │   │   │   ├── hi.json
│   │   │   │   │   │   │   ├── it.json
│   │   │   │   │   │   │   ├── ko.json
│   │   │   │   │   │   │   ├── nb.json
│   │   │   │   │   │   │   ├── nemeth.json
│   │   │   │   │   │   │   ├── nn.json
│   │   │   │   │   │   │   └── sv.json
│   │   │   │   │   │   ├── require.d.mts
│   │   │   │   │   │   ├── require.mjs
│   │   │   │   │   │   └── speech-worker.js
│   │   │   │   │   ├── ui/
│   │   │   │   │   │   ├── lazy.js
│   │   │   │   │   │   ├── menu.js
│   │   │   │   │   │   └── safe.js
│   │   │   │   │   ├── CONTRIBUTING.md
│   │   │   │   │   ├── core.js
│   │   │   │   │   ├── LICENSE
│   │   │   │   │   ├── loader.js
│   │   │   │   │   ├── mml-chtml-nofont.js
│   │   │   │   │   ├── mml-chtml.js
│   │   │   │   │   ├── mml-svg-nofont.js
│   │   │   │   │   ├── mml-svg.js
│   │   │   │   │   ├── node-main-setup.mjs
│   │   │   │   │   ├── node-main.cjs
│   │   │   │   │   ├── node-main.js
│   │   │   │   │   ├── node-main.mjs
│   │   │   │   │   ├── package.json
│   │   │   │   │   ├── README.md
│   │   │   │   │   ├── require.mjs
│   │   │   │   │   ├── startup.js
│   │   │   │   │   ├── tex-chtml-nofont.js
│   │   │   │   │   ├── tex-chtml.js
│   │   │   │   │   ├── tex-mml-chtml-nofont.js
│   │   │   │   │   ├── tex-mml-chtml.js
│   │   │   │   │   ├── tex-mml-svg-nofont.js
│   │   │   │   │   ├── tex-mml-svg.js
│   │   │   │   │   ├── tex-svg-nofont.js
│   │   │   │   │   └── tex-svg.js
│   │   │   │   ├── cubism4.min.js
│   │   │   │   ├── live2dcubismcore.min.js
│   │   │   │   └── pixi.min.js
│   │   │   ├── app.js
│   │   │   ├── favicon.svg
│   │   │   ├── index.html
│   │   │   └── pcm-recorder-worklet.js
│   │   ├── __init__.py
│   │   ├── create_app.py
│   │   ├── runtime.py
│   │   ├── schemas.py
│   │   └── state.py
│   ├── asr/
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── openai_transcriptions.py
│   │   │   └── sherpa_sense_voice.py
│   │   ├── vad/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── silero.py
│   │   ├── __init__.py
│   │   ├── audio.py
│   │   ├── factory.py
│   │   ├── models.py
│   │   ├── realtime.py
│   │   ├── service.py
│   │   └── sherpa.py
│   ├── channels/
│   │   ├── platforms/
│   │   │   ├── __init__.py
│   │   │   ├── console.py
│   │   │   ├── qq.py
│   │   │   └── telegram.py
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── bus.py
│   │   ├── config.py
│   │   ├── manager.py
│   │   ├── registry.py
│   │   └── types.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── chat.py
│   │   ├── common.py
│   │   ├── gateway.py
│   │   ├── main.py
│   │   ├── session_commands.py
│   │   └── trace.py
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── bindings.py
│   │   ├── dispatcher.py
│   │   ├── help.py
│   │   ├── parsing.py
│   │   ├── role.py
│   │   ├── route_mode.py
│   │   ├── route_sessions.py
│   │   ├── runtime.py
│   │   └── saved_sessions.py
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── delivery.py
│   │   ├── route_sessions.py
│   │   ├── runtime.py
│   │   └── session_service.py
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── console.py
│   │   ├── conversion.py
│   │   ├── imports.py
│   │   ├── settings.py
│   │   └── support.py
│   ├── orchestration/
│   │   ├── __init__.py
│   │   ├── coordinator.py
│   │   ├── decision.py
│   │   ├── jobs.py
│   │   ├── roleplay.py
│   │   ├── roles.py
│   │   └── route_modes.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── openai_compatible.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── agent_traces.py
│   │   ├── bootstrap.py
│   │   ├── scheduled_tasks.py
│   │   ├── session_runner.py
│   │   ├── session_service.py
│   │   ├── sessions.py
│   │   ├── settings.py
│   │   ├── system_prompt.py
│   │   └── turns.py
│   ├── scheduling/
│   │   ├── cron/
│   │   │   ├── __init__.py
│   │   │   ├── parser.py
│   │   │   ├── service.py
│   │   │   └── types.py
│   │   ├── heartbeat/
│   │   │   ├── __init__.py
│   │   │   └── service.py
│   │   └── __init__.py
│   ├── skill_support/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── parsing.py
│   │   ├── registry.py
│   │   └── tools.py
│   ├── skills/
│   │   ├── docx/
│   │   │   ├── scripts/
│   │   │   │   ├── office/
│   │   │   │   │   ├── helpers/
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── merge_runs.py
│   │   │   │   │   │   └── simplify_redlines.py
│   │   │   │   │   ├── schemas/
│   │   │   │   │   │   ├── ecma/
│   │   │   │   │   │   │   └── fouth-edition/
│   │   │   │   │   │   │       ├── opc-contentTypes.xsd
│   │   │   │   │   │   │       ├── opc-coreProperties.xsd
│   │   │   │   │   │   │       ├── opc-digSig.xsd
│   │   │   │   │   │   │       └── opc-relationships.xsd
│   │   │   │   │   │   ├── ISO-IEC29500-4_2016/
│   │   │   │   │   │   │   ├── dml-chart.xsd
│   │   │   │   │   │   │   ├── dml-chartDrawing.xsd
│   │   │   │   │   │   │   ├── dml-diagram.xsd
│   │   │   │   │   │   │   ├── dml-lockedCanvas.xsd
│   │   │   │   │   │   │   ├── dml-main.xsd
│   │   │   │   │   │   │   ├── dml-picture.xsd
│   │   │   │   │   │   │   ├── dml-spreadsheetDrawing.xsd
│   │   │   │   │   │   │   ├── dml-wordprocessingDrawing.xsd
│   │   │   │   │   │   │   ├── pml.xsd
│   │   │   │   │   │   │   ├── shared-additionalCharacteristics.xsd
│   │   │   │   │   │   │   ├── shared-bibliography.xsd
│   │   │   │   │   │   │   ├── shared-commonSimpleTypes.xsd
│   │   │   │   │   │   │   ├── shared-customXmlDataProperties.xsd
│   │   │   │   │   │   │   ├── shared-customXmlSchemaProperties.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesCustom.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesExtended.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesVariantTypes.xsd
│   │   │   │   │   │   │   ├── shared-math.xsd
│   │   │   │   │   │   │   ├── shared-relationshipReference.xsd
│   │   │   │   │   │   │   ├── sml.xsd
│   │   │   │   │   │   │   ├── vml-main.xsd
│   │   │   │   │   │   │   ├── vml-officeDrawing.xsd
│   │   │   │   │   │   │   ├── vml-presentationDrawing.xsd
│   │   │   │   │   │   │   ├── vml-spreadsheetDrawing.xsd
│   │   │   │   │   │   │   ├── vml-wordprocessingDrawing.xsd
│   │   │   │   │   │   │   ├── wml.xsd
│   │   │   │   │   │   │   └── xml.xsd
│   │   │   │   │   │   ├── mce/
│   │   │   │   │   │   │   └── mc.xsd
│   │   │   │   │   │   └── microsoft/
│   │   │   │   │   │       ├── wml-2010.xsd
│   │   │   │   │   │       ├── wml-2012.xsd
│   │   │   │   │   │       ├── wml-2018.xsd
│   │   │   │   │   │       ├── wml-cex-2018.xsd
│   │   │   │   │   │       ├── wml-cid-2016.xsd
│   │   │   │   │   │       ├── wml-sdtdatahash-2020.xsd
│   │   │   │   │   │       └── wml-symex-2015.xsd
│   │   │   │   │   ├── validators/
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── base.py
│   │   │   │   │   │   ├── docx.py
│   │   │   │   │   │   ├── pptx.py
│   │   │   │   │   │   └── redlining.py
│   │   │   │   │   ├── pack.py
│   │   │   │   │   ├── soffice.py
│   │   │   │   │   ├── unpack.py
│   │   │   │   │   └── validate.py
│   │   │   │   ├── templates/
│   │   │   │   │   ├── comments.xml
│   │   │   │   │   ├── commentsExtended.xml
│   │   │   │   │   ├── commentsExtensible.xml
│   │   │   │   │   ├── commentsIds.xml
│   │   │   │   │   └── people.xml
│   │   │   │   ├── __init__.py
│   │   │   │   ├── accept_changes.py
│   │   │   │   └── comment.py
│   │   │   ├── LICENSE.txt
│   │   │   └── SKILL.md
│   │   ├── news/
│   │   │   └── SKILL.md
│   │   ├── pdf/
│   │   │   ├── scripts/
│   │   │   │   ├── check_bounding_boxes.py
│   │   │   │   ├── check_fillable_fields.py
│   │   │   │   ├── convert_pdf_to_images.py
│   │   │   │   ├── create_validation_image.py
│   │   │   │   ├── extract_form_field_info.py
│   │   │   │   ├── extract_form_structure.py
│   │   │   │   ├── fill_fillable_fields.py
│   │   │   │   └── fill_pdf_form_with_annotations.py
│   │   │   ├── forms.md
│   │   │   ├── LICENSE.txt
│   │   │   ├── reference.md
│   │   │   └── SKILL.md
│   │   ├── pptx/
│   │   │   ├── scripts/
│   │   │   │   ├── office/
│   │   │   │   │   ├── helpers/
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── merge_runs.py
│   │   │   │   │   │   └── simplify_redlines.py
│   │   │   │   │   ├── schemas/
│   │   │   │   │   │   ├── ecma/
│   │   │   │   │   │   │   └── fouth-edition/
│   │   │   │   │   │   │       ├── opc-contentTypes.xsd
│   │   │   │   │   │   │       ├── opc-coreProperties.xsd
│   │   │   │   │   │   │       ├── opc-digSig.xsd
│   │   │   │   │   │   │       └── opc-relationships.xsd
│   │   │   │   │   │   ├── ISO-IEC29500-4_2016/
│   │   │   │   │   │   │   ├── dml-chart.xsd
│   │   │   │   │   │   │   ├── dml-chartDrawing.xsd
│   │   │   │   │   │   │   ├── dml-diagram.xsd
│   │   │   │   │   │   │   ├── dml-lockedCanvas.xsd
│   │   │   │   │   │   │   ├── dml-main.xsd
│   │   │   │   │   │   │   ├── dml-picture.xsd
│   │   │   │   │   │   │   ├── dml-spreadsheetDrawing.xsd
│   │   │   │   │   │   │   ├── dml-wordprocessingDrawing.xsd
│   │   │   │   │   │   │   ├── pml.xsd
│   │   │   │   │   │   │   ├── shared-additionalCharacteristics.xsd
│   │   │   │   │   │   │   ├── shared-bibliography.xsd
│   │   │   │   │   │   │   ├── shared-commonSimpleTypes.xsd
│   │   │   │   │   │   │   ├── shared-customXmlDataProperties.xsd
│   │   │   │   │   │   │   ├── shared-customXmlSchemaProperties.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesCustom.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesExtended.xsd
│   │   │   │   │   │   │   ├── shared-documentPropertiesVariantTypes.xsd
│   │   │   │   │   │   │   ├── shared-math.xsd
│   │   │   │   │   │   │   ├── shared-relationshipReference.xsd
│   │   │   │   │   │   │   ├── sml.xsd
│   │   │   │   │   │   │   ├── vml-main.xsd
│   │   │   │   │   │   │   ├── vml-officeDrawing.xsd
│   │   │   │   │   │   │   ├── vml-presentationDrawing.xsd
│   │   │   │   │   │   │   ├── vml-spreadsheetDrawing.xsd
│   │   │   │   │   │   │   ├── vml-wordprocessingDrawing.xsd
│   │   │   │   │   │   │   ├── wml.xsd
│   │   │   │   │   │   │   └── xml.xsd
│   │   │   │   │   │   ├── mce/
│   │   │   │   │   │   │   └── mc.xsd
│   │   │   │   │   │   └── microsoft/
│   │   │   │   │   │       ├── wml-2010.xsd
│   │   │   │   │   │       ├── wml-2012.xsd
│   │   │   │   │   │       ├── wml-2018.xsd
│   │   │   │   │   │       ├── wml-cex-2018.xsd
│   │   │   │   │   │       ├── wml-cid-2016.xsd
│   │   │   │   │   │       ├── wml-sdtdatahash-2020.xsd
│   │   │   │   │   │       └── wml-symex-2015.xsd
│   │   │   │   │   ├── validators/
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── base.py
│   │   │   │   │   │   ├── docx.py
│   │   │   │   │   │   ├── pptx.py
│   │   │   │   │   │   └── redlining.py
│   │   │   │   │   ├── pack.py
│   │   │   │   │   ├── soffice.py
│   │   │   │   │   ├── unpack.py
│   │   │   │   │   └── validate.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── add_slide.py
│   │   │   │   ├── clean.py
│   │   │   │   └── thumbnail.py
│   │   │   ├── editing.md
│   │   │   ├── LICENSE.txt
│   │   │   ├── pptxgenjs.md
│   │   │   └── SKILL.md
│   │   ├── scrapling/
│   │   │   ├── examples/
│   │   │   │   ├── 01_fetcher_session.py
│   │   │   │   ├── 02_dynamic_session.py
│   │   │   │   ├── 03_stealthy_session.py
│   │   │   │   ├── 04_spider.py
│   │   │   │   └── README.md
│   │   │   ├── references/
│   │   │   │   ├── fetching/
│   │   │   │   │   ├── choosing.md
│   │   │   │   │   ├── dynamic.md
│   │   │   │   │   ├── static.md
│   │   │   │   │   └── stealthy.md
│   │   │   │   ├── parsing/
│   │   │   │   │   ├── adaptive.md
│   │   │   │   │   ├── main_classes.md
│   │   │   │   │   └── selection.md
│   │   │   │   ├── spiders/
│   │   │   │   │   ├── advanced.md
│   │   │   │   │   ├── architecture.md
│   │   │   │   │   ├── getting-started.md
│   │   │   │   │   ├── proxy-blocking.md
│   │   │   │   │   ├── requests-responses.md
│   │   │   │   │   └── sessions.md
│   │   │   │   ├── mcp-server.md
│   │   │   │   └── migrating_from_beautifulsoup.md
│   │   │   ├── LICENSE.txt
│   │   │   └── SKILL.md
│   │   ├── skill-creator/
│   │   │   ├── agents/
│   │   │   │   ├── analyzer.md
│   │   │   │   ├── comparator.md
│   │   │   │   └── grader.md
│   │   │   ├── assets/
│   │   │   │   └── eval_review.html
│   │   │   ├── eval-viewer/
│   │   │   │   ├── generate_review.py
│   │   │   │   └── viewer.html
│   │   │   ├── references/
│   │   │   │   └── schemas.md
│   │   │   ├── scripts/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── aggregate_benchmark.py
│   │   │   │   ├── generate_report.py
│   │   │   │   ├── improve_description.py
│   │   │   │   ├── package_skill.py
│   │   │   │   ├── quick_validate.py
│   │   │   │   ├── run_eval.py
│   │   │   │   ├── run_loop.py
│   │   │   │   └── utils.py
│   │   │   ├── LICENSE.txt
│   │   │   └── SKILL.md
│   │   ├── weather/
│   │   │   └── SKILL.md
│   │   └── xlsx/
│   │       ├── scripts/
│   │       │   ├── office/
│   │       │   │   ├── helpers/
│   │       │   │   │   ├── __init__.py
│   │       │   │   │   ├── merge_runs.py
│   │       │   │   │   └── simplify_redlines.py
│   │       │   │   ├── schemas/
│   │       │   │   │   ├── ecma/
│   │       │   │   │   │   └── fouth-edition/
│   │       │   │   │   │       ├── opc-contentTypes.xsd
│   │       │   │   │   │       ├── opc-coreProperties.xsd
│   │       │   │   │   │       ├── opc-digSig.xsd
│   │       │   │   │   │       └── opc-relationships.xsd
│   │       │   │   │   ├── ISO-IEC29500-4_2016/
│   │       │   │   │   │   ├── dml-chart.xsd
│   │       │   │   │   │   ├── dml-chartDrawing.xsd
│   │       │   │   │   │   ├── dml-diagram.xsd
│   │       │   │   │   │   ├── dml-lockedCanvas.xsd
│   │       │   │   │   │   ├── dml-main.xsd
│   │       │   │   │   │   ├── dml-picture.xsd
│   │       │   │   │   │   ├── dml-spreadsheetDrawing.xsd
│   │       │   │   │   │   ├── dml-wordprocessingDrawing.xsd
│   │       │   │   │   │   ├── pml.xsd
│   │       │   │   │   │   ├── shared-additionalCharacteristics.xsd
│   │       │   │   │   │   ├── shared-bibliography.xsd
│   │       │   │   │   │   ├── shared-commonSimpleTypes.xsd
│   │       │   │   │   │   ├── shared-customXmlDataProperties.xsd
│   │       │   │   │   │   ├── shared-customXmlSchemaProperties.xsd
│   │       │   │   │   │   ├── shared-documentPropertiesCustom.xsd
│   │       │   │   │   │   ├── shared-documentPropertiesExtended.xsd
│   │       │   │   │   │   ├── shared-documentPropertiesVariantTypes.xsd
│   │       │   │   │   │   ├── shared-math.xsd
│   │       │   │   │   │   ├── shared-relationshipReference.xsd
│   │       │   │   │   │   ├── sml.xsd
│   │       │   │   │   │   ├── vml-main.xsd
│   │       │   │   │   │   ├── vml-officeDrawing.xsd
│   │       │   │   │   │   ├── vml-presentationDrawing.xsd
│   │       │   │   │   │   ├── vml-spreadsheetDrawing.xsd
│   │       │   │   │   │   ├── vml-wordprocessingDrawing.xsd
│   │       │   │   │   │   ├── wml.xsd
│   │       │   │   │   │   └── xml.xsd
│   │       │   │   │   ├── mce/
│   │       │   │   │   │   └── mc.xsd
│   │       │   │   │   └── microsoft/
│   │       │   │   │       ├── wml-2010.xsd
│   │       │   │   │       ├── wml-2012.xsd
│   │       │   │   │       ├── wml-2018.xsd
│   │       │   │   │       ├── wml-cex-2018.xsd
│   │       │   │   │       ├── wml-cid-2016.xsd
│   │       │   │   │       ├── wml-sdtdatahash-2020.xsd
│   │       │   │   │       └── wml-symex-2015.xsd
│   │       │   │   ├── validators/
│   │       │   │   │   ├── __init__.py
│   │       │   │   │   ├── base.py
│   │       │   │   │   ├── docx.py
│   │       │   │   │   ├── pptx.py
│   │       │   │   │   └── redlining.py
│   │       │   │   ├── pack.py
│   │       │   │   ├── soffice.py
│   │       │   │   ├── unpack.py
│   │       │   │   └── validate.py
│   │       │   └── recalc.py
│   │       ├── LICENSE.txt
│   │       └── SKILL.md
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── builtin.py
│   │   ├── cron.py
│   │   ├── filesystem.py
│   │   ├── git.py
│   │   ├── media.py
│   │   ├── memory.py
│   │   ├── planning.py
│   │   ├── shell.py
│   │   └── web.py
│   ├── tts/
│   │   ├── providers/
│   │   │   ├── kokoro/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── model_manager.py
│   │   │   │   ├── provider.py
│   │   │   │   ├── runtime.py
│   │   │   │   └── voices.py
│   │   │   ├── __init__.py
│   │   │   ├── edge.py
│   │   │   └── openai_compatible.py
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── service.py
│   │   ├── synthesis.py
│   │   └── text.py
│   ├── __init__.py
│   ├── __main__.py
│   ├── agent.py
│   ├── attachments.py
│   ├── config.py
│   ├── images.py
│   ├── models.py
│   ├── naming.py
│   ├── speech_assets.py
│   └── turn_inputs.py
├── skills/
│   ├── echobot-development/
│   │   ├── references/
│   │   │   └── architecture.md
│   │   └── SKILL.md
│   └── echobot-skill-authoring/
│       ├── references/
│       │   └── runtime.md
│       └── SKILL.md
├── tests/
│   ├── conftest.py
│   ├── test_agent_traces.py
│   ├── test_agent.py
│   ├── test_app_api.py
│   ├── test_asr_openai.py
│   ├── test_asr.py
│   ├── test_channel_images.py
│   ├── test_chat_agent.py
│   ├── test_commands.py
│   ├── test_config.py
│   ├── test_coordinator.py
│   ├── test_decision.py
│   ├── test_gateway.py
│   ├── test_images.py
│   ├── test_roleplay.py
│   ├── test_roles.py
│   ├── test_scheduler.py
│   ├── test_sessions.py
│   ├── test_skill_support.py
│   ├── test_speech_assets.py
│   ├── test_tools.py
│   └── test_tts.py
├── .env.example
├── .gitignore
├── .ignore
├── AGENTS.md
├── LICENSE
├── pytest.ini
├── README_EN.md
├── README.md
└── requirements.txt
