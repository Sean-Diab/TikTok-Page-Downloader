# reverse_links.py

def reverse_links(input_file="links.txt", output_file="reversed_links.txt"):
    # Read all lines from the input file
    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Remove trailing newlines and reverse order
    lines = [line.strip() for line in lines if line.strip()]
    reversed_lines = lines[::-1]

    # Write back to the output file
    with open(output_file, "w", encoding="utf-8") as f:
        for line in reversed_lines:
            f.write(line + "\n")

    print(f"Reversed links saved to {output_file}")


if __name__ == "__main__":
    reverse_links()
