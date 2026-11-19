# README 데모 GIF 생성용 (https://github.com/charmbracelet/vhs)
#   brew install vhs
#   vhs demo.tape      → assets/demo.gif 생성
Output assets/demo.gif
Set FontSize 18
Set Width 1100
Set Height 600
Set Theme "Catppuccin Mocha"

Type "python3 tokenbot.py status"
Enter
Sleep 2s
Type "python3 tokenbot.py plan"
Enter
Sleep 3s
