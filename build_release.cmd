@echo off
SETLOCAL EnableDelayedExpansion

:: Configuration - Set your GitHub username here
set GITHUB_USER=svaningelgem

:: Check if version is provided
if "%1"=="" (
    echo Error: Please provide a version number
    echo Usage: %0 VERSION
    echo Example: %0 3.4.0
    exit /b 1
)

:: Variables
set VERSION=%1
set IMAGE_NAME=flaresolverr
set FULL_IMAGE_NAME=ghcr.io/%GITHUB_USER%/%IMAGE_NAME%

echo Building Docker image v%VERSION%...
docker build -t %FULL_IMAGE_NAME%:%VERSION% .
if errorlevel 1 (
    echo Error: Docker build failed
    exit /b 1
)

echo Tagging latest version...
docker tag %FULL_IMAGE_NAME%:%VERSION% %FULL_IMAGE_NAME%:latest

echo Logging in to GitHub Container Registry...
echo Please enter your GitHub Personal Access Token:
docker login ghcr.io -u %GITHUB_USER%
if errorlevel 1 (
    echo Error: Login failed
    exit /b 1
)

echo Publishing images to GitHub Container Registry...
docker push %FULL_IMAGE_NAME%:%VERSION%
if errorlevel 1 (
    echo Error: Failed to push version tag
    exit /b 1
)

docker push %FULL_IMAGE_NAME%:latest
if errorlevel 1 (
    echo Error: Failed to push latest tag
    exit /b 1
)

echo Successfully published Docker image to GitHub Container Registry
echo Image: %FULL_IMAGE_NAME%:%VERSION%
echo Image: %FULL_IMAGE_NAME%:latest
echo Run as: docker run -d --name %IMAGE_NAME% --restart unless-stopped -p 8191:8191 %FULL_IMAGE_NAME%:latest
exit /b 0