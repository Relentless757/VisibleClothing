@echo off
rem Rebuild the mod from fitting\VisibleClothing_Fitting.blend (from PowerShell or cmd). Same arguments as
rem rebuild_from_fitting.sh, e.g.:  tools\rebuild_from_fitting.cmd ClothingHandsT1 --install
rem Runs Git Bash explicitly: plain "bash" in PowerShell is WSL, which cannot see the Windows paths.
"C:\Program Files\Git\bin\bash.exe" "%~dp0rebuild_from_fitting.sh" %*
