.PHONY: all clean pdf watch

all: pdf

pdf:
	@mkdir -p build
	pdflatex -interaction=nonstopmode -output-directory=build main.tex > /dev/null 2>&1 || true
	cp references.bib IEEEtranS.bst build/
	cd build && bibtex main > /dev/null 2>&1 || true
	pdflatex -interaction=nonstopmode -output-directory=build main.tex > /dev/null 2>&1 || true
	pdflatex -interaction=nonstopmode -output-directory=build main.tex > /dev/null 2>&1 || true
	cp build/main.pdf main.pdf
	@echo "✓ PDF generated: main.pdf"

watch:
	while true; do \
		inotifywait -e modify main.tex && make pdf; \
	done

clean:
	rm -rf build/ main.pdf

open: pdf
	open main.pdf || xdg-open main.pdf 2>/dev/null || echo "Please open main.pdf manually"

.SILENT:
