<p align="center">
  <img src="https://raw.githubusercontent.com/gabe565/TronbytAssistant/main/logo.png">
</p>
</br>

Display notifications from Home Assistant to Tronbyt devices using this integration.

# Installation

## HACS
You can add this repository to HACS if you have it installed by adding this link to your custom repository (click the 3 dots at the top right):
```txt
https://github.com/gabe565/TronbytAssistant
```
Then just search for TronbytAssistant and install the integration. You will have to restart HomeAssistant.

This is the recommended installation method since HACS will prompt you when an update is available.

## Manual
Copy the entirety of `custom_components/tronbytassistant` to your `/config/custom_components` folder. You can do this using ***Samba***.

## Configuration
1. Navigate to **Settings → Devices & Services → Add Integration** and search for **TronbytAssistant**.
2. Add each Tronbyt device by supplying the Device ID, Key, optional display name, and the base URL of your Tronbyt server (for example `https://tron.example.com`).
3. Finish the flow; the integration will verify the devices and update the service selectors automatically.

# Features

## Entities
- Each Tronbyt device exposes a light entity that controls display brightness (0–100%).
- Auto-dimming is available as a switch entity so you can toggle adaptive brightness in automations.

## Services
### TronbytAssistant: Push
1. Select the radio button for *Built-in*.
2. Use the *Content* dropdown to select from the built in notifications served by your Tronbyt backend.
3. Select your device(s) and run the action.

### TronbytAssistant: Text
1. Select the radio buttom for *Text*
2. In the *Content* box, enter the text you want displayed. You can also select from the avaialble fonts and colors as well as static text or scrolling.
3. Select your device(s) and run the action. You should see your text on the screen.
   
### TronbytAssistant: Delete
1. Enter the content ID of the app you published and device name.
2. Select you device(s) and run the action. The app should now be removed from your rotation.
3. If the app you tried to delete is not installed on the Tronbyt, you will see a list of apps that are available for deletion. Only apps that you have sent through Home Assistant will show up for deletion.

# Things to note
## Passing arguments
Passing arguments to your app can be helpful because it removes the need to hard code values. It also allows you to pass in templated values directly to your apps. The following example is taken from the Pixlet docs and is how you would use these varibles inside your app:
```
def main(config):
    who = config.get("who")
    print("Hello, %s" % who)
```
This example has a varible "who", which can be used as the **key=value** pair **who=me** which will pass the value **me** into your star app. Here is an example I use for the Movie Night app, which has two varibles **time** and **title** and uses HomeAssistant's template values:
```
  ... other service data here
  arguments: >-
    time={{ (now().strftime('%Y-%m-%d') + 'T' +
    states('input_datetime.movie_night_time') + now().isoformat()[-6:]) 
    }};title={{ states('input_text.movie_night_movie') }}
```

# Troubleshooting
The action should do a few checks when you run it and give feedback on what went wrong. If you need deeper details, check the logs on your Tronbyt server as well as Home Assistant's logs for HTTP errors.
