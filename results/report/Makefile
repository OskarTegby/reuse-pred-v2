SRC_DIR  := src
BUILD_DIR := build
MAIN     := report
PDF      := $(BUILD_DIR)/$(MAIN).pdf
TEX      := $(SRC_DIR)/$(MAIN).tex

.PHONY: all clean

all: $(PDF)

$(PDF): $(TEX) | $(BUILD_DIR)
	cd $(SRC_DIR) && pdflatex -output-directory=../$(BUILD_DIR) -interaction=nonstopmode $(MAIN).tex
	cd $(SRC_DIR) && pdflatex -output-directory=../$(BUILD_DIR) -interaction=nonstopmode $(MAIN).tex

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
