import { describe, expect, test } from "vitest";

import { stripExtension } from "./stripExtension";

interface ExtensionScenario {
    behavior: string;
    examples: [filename: string, expected: string][];
}

describe("stripExtension", () => {
    describe.each<ExtensionScenario>([
        {
            behavior: "strips single extensions",
            examples: [
                ["sample.fastq", "sample"],
                ["data.bam", "data"],
                ["example.fasta", "example"],
                ["sample.txt", "sample"],
            ],
        },
        {
            behavior: "strips multi-part extensions with secondary extensions",
            examples: [
                ["sample.fastq.gz", "sample"],
                ["data.fasta.tgz", "data"],
                ["example.bam.bz2", "example"],
            ],
        },
        {
            behavior: "handles filenames with multiple dots",
            examples: [
                ["my.sample.fastq.gz", "my.sample"],
                ["test.data.vcf.gz", "test.data"],
                ["dataset.v1.bam.bz2", "dataset.v1"],
            ],
        },
        {
            behavior: "preserves filenames without dots",
            examples: [["no_extension", "no_extension"]],
        },
        {
            behavior: "preserves significant metadata that resembles an extension",
            examples: [
                ["mycondition1.mysample1234", "mycondition1.mysample1234"],
                ["mycondition1.mysample1234.fastq", "mycondition1.mysample1234"],
                ["mycondition1.mysample1234.fastq.gz", "mycondition1.mysample1234"],
            ],
        },
        {
            behavior: "handles edge cases",
            examples: [
                [".fastq.gz", ""],
                ["file..fastq.gz", "file."],
                ["file.fastq.extra.gz", "file.fastq"],
            ],
        },
    ])("$behavior", ({ examples }) => {
        test.each(examples)("'%s' becomes '%s'", (filename, expected) => {
            expect(stripExtension(filename)).toBe(expected);
        });
    });
});
