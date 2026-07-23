# Homebrew formula for yoink (dev tap)
#
# Usage (once tap exists):
#   brew tap saturninfj/yoink
#   brew install yoink
#
# Until the tap repo exists, you can install from source:
#   brew install --HEAD --build-from-source \
#     https://raw.githubusercontent.com/saturninfj/yoink/main/packaging/homebrew/yoink.rb

class Yoink < Formula
  include Language::Python::Virtualenv

  desc "Multi-segment HTTP downloader with browser integration. OSS IDM alternative."
  homepage "https://github.com/saturninfj/yoink"
  url "https://github.com/saturninfj/yoink/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_ON_FIRST_RELEASE"
  license "Apache-2.0"
  head "https://github.com/saturninfj/yoink.git", branch: "main"

  depends_on "python@3.12"

  resource "yt-dlp" do
    url "https://files.pythonhosted.org/packages/source/y/yt-dlp/yt-dlp-2026.7.4.tar.gz"
    sha256 "REPLACE_ON_FIRST_RELEASE"
  end

  def install
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install resources unless resources.empty?
    venv.pip_install_and_link buildpath
  end

  test do
    assert_match "yoink", shell_output("#{bin}/yoink --version")
  end
end
